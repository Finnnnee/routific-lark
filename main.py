import os
import requests
from fastapi import FastAPI, Request

# ==================== 环境变量 ====================
LARK_APP_ID = os.getenv("LARK_APP_ID")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET")
LARK_BASE_TOKEN = os.getenv("LARK_BASE_TOKEN")
LARK_TABLE_ID = os.getenv("LARK_TABLE_ID")
ROUTIFIC_API_TOKEN = os.getenv("ROUTIFIC_API_TOKEN")
LARK_ALERT_WEBHOOK = os.getenv("LARK_ALERT_WEBHOOK")

WAREHOUSE_ADDRESS = "55 Progress Ave, Toronto, ON M1P2Y7"

app = FastAPI(title="单订单配送")

# ==================== 飞书告警 ====================
def send_alert(title, msg):
    if not LARK_ALERT_WEBHOOK:
        return
    try:
        requests.post(LARK_ALERT_WEBHOOK, json={
            "msg_type": "text",
            "content": {"text": f"{title}\n{msg}"}
        }, timeout=3)
    except:
        pass

# ==================== 核心：路线规划 ====================
def plan_route(order):
    if not ROUTIFIC_API_TOKEN:
        send_alert("🚨 错误", "未配置 ROUTIFIC_API_TOKEN")
        return None

    url = "https://api.routific.com/v1/vrp"
    headers = {
        "Authorization": f"Bearer {ROUTIFIC_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "visits": {
            order["order_id"]: {
                "location": {"address": order["address"]},
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

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10).json()
        if "solution" not in res:
            send_alert("🚨 路线规划失败", f"Routific 返回：{res}")
            return None
        return res["solution"]["d1"]
    except Exception as e:
        send_alert("🚨 接口异常", str(e))
        return None

# ==================== 飞书更新 ====================
def update_record(record_id, map_url, eta):
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
            json={"fields": {"AI规划路线": map_url, "预计到达时间": eta}}
        )
    except:
        pass

# ==================== 唯一入口 ====================
@app.post("/lark-webhook")
async def lark_webhook(request: Request):
    try:
        order = await request.json()
        result = plan_route(order)
        if not result:
            return {"code": 500, "msg": "路线规划失败"}

        for stop in result.get("route", []):
            if stop["type"] == "VISIT":
                update_record(
                    order.get("record_id"),
                    result.get("google_map_url", ""),
                    stop.get("arrival_time", "暂无")
                )
        return {"code": 200, "msg": "✅ 成功"}
    except Exception as e:
        send_alert("🚨 服务异常", str(e))
        return {"code": 500, "msg": str(e)}

@app.get("/")
def index():
    return {"status": "running", "token_configured": bool(ROUTIFIC_API_TOKEN)}
