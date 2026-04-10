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

# 你的仓库地址
WAREHOUSE_ADDRESS = "55 Progress Ave, Toronto, ON M1P 2Y7"

app = FastAPI(title="Lark + Routific Platform API")

# ==================== 告警 ====================
def send_alert(title, msg):
    if LARK_ALERT_WEBHOOK:
        try:
            requests.post(LARK_ALERT_WEBHOOK, json={
                "msg_type": "text",
                "content": {"text": f"{title}\n{msg}"}
            }, timeout=3)
        except:
            pass

# ==================== 新版 Routific Platform API ====================
def optimize_route(order):
    url = "https://platform.routific.com/api/v1/optimize"
    headers = {
        "Authorization": f"Bearer {ROUTIFIC_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "visits": [
            {
                "id": order["order_id"],
                "location": {
                    "address": order["address"]
                },
                "timeWindows": [{"start": "08:00", "end": "20:00"}],
                "serviceDuration": 300
            }
        ],
        "vehicles": [
            {
                "id": "driver",
                "startLocation": {
                    "address": WAREHOUSE_ADDRESS
                },
                "endLocation": {
                    "address": WAREHOUSE_ADDRESS
                }
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        print("Routific 返回:", resp.status_code, resp.text)
        return resp.json()
    except Exception as e:
        send_alert("🚨 路线规划异常", str(e))
        return None

# ==================== 飞书更新 ====================
def update_lark(record_id, eta):
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
            json={"fields": {"预计到达时间": eta}}
        )
    except:
        pass

# ==================== 主入口 ====================
@app.post("/lark-webhook")
async def webhook(request: Request):
    try:
        order = await request.json()
        result = optimize_route(order)

        if not result or "solutions" not in result:
            return {"code": 500, "msg": "规划失败"}

        solution = result["solutions"][0]
        eta = solution.get("arrivalTime", "暂无")
        update_lark(order.get("record_id"), eta)

        return {"code": 200, "msg": "✅ 路线规划完成"}

    except Exception as e:
        send_alert("🚨 处理失败", str(e))
        return {"code": 500, "msg": str(e)}

@app.get("/")
def home():
    return {"status": "running"}
