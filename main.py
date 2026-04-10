import os
import json
import requests
from fastapi import FastAPI, Request

# ==================== 环境变量 ====================
LARK_APP_ID = os.getenv("LARK_APP_ID")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET")
LARK_BASE_TOKEN = os.getenv("LARK_BASE_TOKEN")
LARK_TABLE_ID = os.getenv("LARK_TABLE_ID")
ROUTIFIC_API_TOKEN = os.getenv("ROUTIFIC_API_TOKEN")
LARK_ALERT_WEBHOOK = os.getenv("LARK_ALERT_WEBHOOK")

WAREHOUSE_ADDRESS = "55 Progress Ave, Toronto, ON M1P 2Y7"

app = FastAPI(title="最终稳定版")

# ==================== 飞书告警 ====================
def send_alert(title, msg):
    if not LARK_ALERT_WEBHOOK:
        return
    try:
        requests.post(LARK_ALERT_WEBHOOK, json={
            "msg_type": "text",
            "content": {"text": f"[{title}] {msg}"}
        }, timeout=3)
    except:
        pass

# ==================== 【正确】Routific API ====================
def plan_route(order):
    try:
        order_id = order.get("order_id")
        address = order.get("address")
        record_id = order.get("record_id")

        if not address:
            send_alert("错误", "无地址")
            return None

        # ✅ 正确官方地址
        url = "https://api.routific.com/v1/vrp"

        headers = {
            "Authorization": f"Bearer {ROUTIFIC_API_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "visits": {
                order_id: {
                    "location": {"address": address},
                    "start": "08:00",
                    "end": "20:00",
                    "duration": 5
                }
            },
            "fleet": {
                "d1": {
                    "start_location": {"address": WAREHOUSE_ADDRESS},
                    "end_location": {"address": WAREHOUSE_ADDRESS}
                }
            }
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        result = resp.json()
        print("Routific 返回:", result)
        return result.get("solution", {}).get("d1")

    except Exception as e:
        send_alert("路线规划异常", str(e))
        return None

# ==================== 写回飞书 ====================
def update_lark(record_id, eta, map_url=""):
    if not record_id:
        return
    try:
        token_resp = requests.post(
            "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}
        ).json()
        token = token_resp.get("tenant_access_token")
        if not token:
            return

        requests.put(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records/{record_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "fields": {
                    "AI规划路线": map_url,
                    "预计到达时间": eta
                }
            }
        )
    except:
        pass

# ==================== 主入口 ====================
@app.post("/lark-webhook")
async def webhook(request: Request):
    try:
        order = await request.json()
        driver = plan_route(order)

        if not driver:
            return {"code":500,"msg":"失败"}

        map_url = driver.get("google_map_url", "")
        for stop in driver.get("route", []):
            if stop["type"] == "VISIT":
                update_lark(order.get("record_id"), stop.get("arrival_time"), map_url)

        send_alert("✅ 订单完成", "路线规划成功")
        return {"code":200,"msg":"✅ 订单处理完成"}

    except Exception as e:
        send_alert("🚨 系统错误", str(e))
        return {"code":500,"msg":str(e)}

@app.get("/")
def home():
    return {"status":"running"}
