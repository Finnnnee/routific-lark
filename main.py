import os
import json
import requests
from fastapi import FastAPI, Request

# ===================== 环境变量配置（Render 后台配置）=====================
LARK_APP_ID = os.getenv("LARK_APP_ID")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET")
LARK_BASE_TOKEN = os.getenv("LARK_BASE_TOKEN")
LARK_TABLE_ID = os.getenv("LARK_TABLE_ID")
ROUTIFIC_API_TOKEN = os.getenv("ROUTIFIC_API_TOKEN")
LARK_ALERT_WEBHOOK = os.getenv("LARK_ALERT_WEBHOOK")

# 【唯一需要修改】你的仓库地址
WAREHOUSE_ADDRESS = "请替换为你的仓库完整地址（省+市+区+详细地址）"

# 服务初始化
app = FastAPI(title="Lark-Routific 智能配送系统（完整版）", version="3.0")

# ===================== 1. 获取飞书租户凭证 =====================
def get_lark_tenant_token():
    try:
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json"}
        data = {
            "app_id": LARK_APP_ID,
            "app_secret": LARK_APP_SECRET
        }
        response = requests.post(url, headers=headers, json=data, timeout=15)
        res = response.json()
        if res.get("code") == 0:
            return res.get("tenant_access_token", "")
        print(f"飞书Token获取失败：{res}")
        return ""
    except Exception as e:
        print(f"飞书Token异常：{str(e)}")
        return ""

# ===================== 2. 飞书群异常告警 =====================
def send_alert(title, content):
    if not LARK_ALERT_WEBHOOK:
        return
    try:
        msg = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "text", "text": content}]]
                    }
                }
            }
        }
        requests.post(LARK_ALERT_WEBHOOK, json=msg, timeout=5)
    except Exception:
        pass

# ===================== 3. Routific 全局最优路线规划（支持批量+智能排序）=====================
def optimize_routes(orders):
    try:
        url = "https://api.routific.com/v1/vrp"
        headers = {
            "Authorization": f"Bearer {ROUTIFIC_API_TOKEN}",
            "Content-Type": "application/json"
        }

        visits = {}
        for o in orders:
            order_id = o.get("order_id")
            address = o.get("address")
            name = o.get("customer_name")
            if order_id and address:
                visits[order_id] = {
                    "location": {"address": address},
                    "start": "08:00",
                    "end": "20:00",
                    "duration": 10,
                    "notes": f"订单：{order_id} | 客户：{name}"
                }

        payload = {
            "visits": visits,
            "fleet": {
                "delivery_driver": {
                    "start_location": {"address": WAREHOUSE_ADDRESS},
                    "end_location": {"address": WAREHOUSE_ADDRESS},
                    "capacity": 100,
                    "max_distance": 500
                }
            }
        }

        res = requests.post(url, json=payload, timeout=30).json()
        solution = res.get("solution", {})

        if not solution or "delivery_driver" not in solution:
            send_alert("🚨 路径规划失败", f"Routific 返回结果：{res}")
            return None

        return solution["delivery_driver"]

    except Exception as e:
        send_alert("🚨 路线规划异常", str(e))
        return None

# ===================== 4. 写回飞书：路线 + 时间 + 配送排序（Routific 决定）=====================
def update_order(record_id, route_url, eta, sequence=None):
    try:
        token = get_lark_tenant_token()
        if not token:
            send_alert("🚨 飞书更新失败", "无法获取有效 token")
            return

        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records/{record_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        fields = {
            "AI规划路线": route_url,
            "预计到达时间": eta
        }
        if sequence is not None:
            fields["配送排序"] = sequence

        data = {"fields": fields}
        res = requests.put(url, json=data, headers=headers, timeout=15).json()

        if res.get("code") == 0:
            print(f"✅ 飞书更新成功：{record_id}")
        else:
            send_alert("🚨 飞书订单更新失败", f"记录 {record_id} 返回：{res}")
    except Exception as e:
        send_alert("🚨 飞书写入异常", f"记录 {record_id} 错误：{str(e)}")

# ===================== 5. 司机实时位置同步 =====================
def sync_driver_location(order_record_id, lat, lng, update_time):
    try:
        token = get_lark_tenant_token()
        if not token:
            return

        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records/{order_record_id}"
        data = {
            "fields": {
                "司机实时位置": f"{lat},{lng}",
                "最后定位时间": update_time
            }
        }
        requests.put(url, json=data, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except Exception:
        pass

# ===================== 6. 推送飞书卡片给司机 =====================
def send_lark_card_to_driver(driver_user_id, order_id, customer_name, address, route_url, eta, seq=None):
    if not driver_user_id:
        return

    try:
        token = get_lark_tenant_token()
        if not token:
            return

        url = "https://open.larksuite.com/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        seq_text = f"\n**配送顺序**：{seq}" if seq is not None else ""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🚚 新配送任务已规划"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**订单号**：{order_id}\n**客户**：{customer_name}\n**地址**：{address}\n**预计到达**：{eta}{seq_text}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "🧭 一键导航"},
                            "type": "primary",
                            "url": route_url if route_url else "https://map.baidu.com"
                        }
                    ]
                }
            ]
        }

        payload = {
            "receive_id": driver_user_id,
            "content": json.dumps(card, ensure_ascii=False),
            "msg_type": "interactive"
        }

        res = requests.post(url, headers=headers, json=payload, params={"receive_id_type": "user_id"}, timeout=15).json()
        if res.get("code") == 0:
            print(f"✅ 卡片推送成功：{driver_user_id}")
        else:
            print(f"❌ 卡片失败：{res}")
    except Exception as e:
        print(f"推送异常：{str(e)}")

# ===================== 接口 1：单订单触发 =====================
@app.post("/lark-webhook")
async def lark_webhook(request: Request):
    try:
        data = await request.json()
        return await batch_plan({"orders": [data]})
    except Exception as e:
        send_alert("🚨 单订单处理失败", str(e))
        return {"code": 500, "msg": f"异常：{str(e)}"}

# ===================== 接口 2：批量规划（Routific 智能排序）=====================
@app.post("/batch-plan")
async def batch_plan(request: Request):
    data = await request.json()
    orders = data.get("orders", [])

    if not orders:
        return {"code": 400, "msg": "无有效订单"}

    route_data = optimize_routes(orders)
    if not route_data:
        return {"code": 500, "msg": "路线规划失败"}

    full_route_url = route_data.get("google_map_url", "")
    route = route_data.get("route", [])

    for seq, stop in enumerate(route):
        if stop.get("type") != "VISIT":
            continue
        order_id = stop.get("stop_id")
        eta = stop.get("arrival_time", "暂无")

        for o in orders:
            if o.get("order_id") == order_id:
                update_order(
                    o.get("record_id"),
                    full_route_url,
                    eta,
                    sequence=seq + 1
                )
                send_lark_card_to_driver(
                    o.get("driver_user_id"),
                    order_id,
                    o.get("customer_name"),
                    o.get("address"),
                    full_route_url,
                    eta,
                    seq=seq + 1
                )

    return {"code": 200, "msg": "✅ Routific 已完成全局最优规划"}

# ===================== 接口 3：司机实时位置回调 =====================
@app.post("/driver-location")
async def driver_location(request: Request):
    data = await request.json()
    order_record_id = data.get("order_record_id") or data.get("order_id")
    lat = data.get("lat")
    lng = data.get("lng")
    updated_at = data.get("updated_at")

    if order_record_id and lat and lng:
        sync_driver_location(order_record_id, lat, lng, updated_at)
    return {"code": 200, "msg": "位置同步成功"}

# ===================== 健康检查 =====================
@app.get("/")
async def root():
    return {"status": "running", "msg": "Lark-Routific 完整版服务正常"}

# ===================== 启动 =====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
