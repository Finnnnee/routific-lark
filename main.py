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

# 你的仓库地址
WAREHOUSE_ADDRESS = "55 Progress Ave, Toronto, ON M1P 2Y7"

# 服务初始化
app = FastAPI(title="Lark-Routific 单订单配送系统", version="1.0")

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

# ===================== 【单订单】Routific 路线规划 =====================
def optimize_single_route(order):
    try:
        url = "https://api.routific.com/v1/vrp"
        # ✅ 这里强制打印密钥，确保能读到
        print(f"【DEBUG】使用的 Routific Token: {ROUTIFIC_API_TOKEN}")
        
        headers = {
            "Authorization": f"Bearer {ROUTIFIC_API_TOKEN}",
            "Content-Type": "application/json"
        }

        order_id = order.get("order_id")
        address = order.get("address")
        customer_name = order.get("customer_name")

        if not order_id or not address:
            send_alert("🚨 订单无效", "缺少 order_id 或 address")
            return None

        payload = {
            "visits": {
                order_id: {
                    "location": {"address": address},
                    "start": "08:00",
                    "end": "20:00",
                    "duration": 10,
                    "notes": f"订单：{order_id} | 客户：{customer_name}"
                }
            },
            "fleet": {
                "driver": {
                    "start_location": {"address": WAREHOUSE_ADDRESS},
                    "end_location": {"address": WAREHOUSE_ADDRESS}
                }
            }
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        res = response.json()
        print("Routific 返回:", res)

        solution = res.get("solution", {})
        if not solution or "driver" not in solution:
            send_alert("🚨 路径规划失败", f"Routific 返回：{res}")
            return None

        return solution["driver"]

    except Exception as e:
        send_alert("🚨 路线规划异常", str(e))
        return None

# ===================== 4. 写回飞书 =====================
def update_order(record_id, route_url, eta):
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

        data = {"fields": fields}
        res = requests.put(url, json=data, headers=headers, timeout=15).json()

        if res.get("code") == 0:
            print(f"✅ 飞书更新成功：{record_id}")
        else:
            send_alert("🚨 飞书订单更新失败", f"记录 {record_id} 返回：{res}")
    except Exception as e:
        send_alert("🚨 飞书写入异常", f"记录 {record_id} 错误：{str(e)}")

# ===================== 6. 推送飞书卡片给司机 =====================
def send_lark_card_to_driver(driver_user_id, order_id, customer_name, address, route_url, eta):
    if not driver_user_id:
        return

    try:
        token = get_lark_tenant_token()
        if not token:
            return

        url = "https://open.larksuite.com/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🚚 新配送任务"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**订单号**：{order_id}\n**客户**：{customer_name}\n**地址**：{address}\n**预计到达**：{eta}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "🧭 导航"},
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

        requests.post(url, headers=headers, json=payload, params={"receive_id_type": "user_id"}, timeout=15)
    except Exception:
        pass

# ===================== 【唯一接口】单订单 Webhook =====================
@app.post("/lark-webhook")
async def lark_webhook(request: Request):
    try:
        data = await request.json()
        route_result = optimize_single_route(data)

        if not route_result:
            return {"code": 500, "msg": "路线规划失败"}

        route = route_result.get("route", [])
        full_route_url = route_result.get("google_map_url", "")

        for stop in route:
            if stop.get("type") == "VISIT":
                eta = stop.get("arrival_time", "暂无")
                update_order(
                    data.get("record_id"),
                    full_route_url,
                    eta
                )
                send_lark_card_to_driver(
                    data.get("driver_user_id"),
                    data.get("order_id"),
                    data.get("customer_name"),
                    data.get("address"),
                    full_route_url,
                    eta
                )

        return {"code": 200, "msg": "✅ 单订单配送规划完成"}

    except Exception as e:
        send_alert("🚨 单订单处理失败", str(e))
        return {"code": 500, "msg": f"异常：{str(e)}"}

# ===================== 健康检查 =====================
@app.get("/")
async def root():
    return {"status": "running", "msg": "单订单服务正常"}

# ===================== 启动 =====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
