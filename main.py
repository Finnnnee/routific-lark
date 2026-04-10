import os
import json
import requests
from fastapi import FastAPI, Request

# ===================== 环境变量 =====================
LARK_APP_ID = os.getenv("LARK_APP_ID")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET")
LARK_BASE_TOKEN = os.getenv("LARK_BASE_TOKEN")
LARK_TABLE_ID = os.getenv("LARK_TABLE_ID")
ROUTIFIC_API_TOKEN = os.getenv("ROUTIFIC_API_TOKEN")
LARK_ALERT_WEBHOOK = os.getenv("LARK_ALERT_WEBHOOK")

WAREHOUSE_ADDRESS = "55 Progress Ave, Toronto, ON M1P 2Y7"

app = FastAPI(title="单订单配送")

# ===================== 工具 =====================
def get_lark_token():
    try:
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).json()
        return res.get("tenant_access_token") if res.get("code") == 0 else None
    except:
        return None

def send_alert(title, msg):
    if LARK_ALERT_WEBHOOK:
        try:
            requests.post(LARK_ALERT_WEBHOOK, json={
                "msg_type": "post",
                "content": {"post": {"zh_cn": {"title": title, "content": [[{"tag": "text", "text": msg}]]}}}
            })
        except:
            pass

# ===================== 单一路线规划 =====================
def route_single(order):
    print("=== DEBUG ===")
    print("TOKEN 读到:", ROUTIFIC_API_TOKEN)  # 你可以去 Logs 看这里

    if not ROUTIFIC_API_TOKEN:
        send_alert("🚨 错误", "ROUTIFIC_API_TOKEN 未配置")
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
                "start": "08:00", "end": "20:00", "duration": 10
            }
        },
        "fleet": {
            "driver": {
                "start_location": {"address": WAREHOUSE_ADDRESS},
                "end_location": {"address": WAREHOUSE_ADDRESS}
            }
        }
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        res = r.json()
        print("Routific 返回:", res)
        return res.get("solution", {}).get("driver")
    except Exception as e:
        send_alert("🚨 路线规划异常", str(e))
        return None

# ===================== 更新飞书 =====================
def update(record_id, url, eta):
    token = get_lark_token()
    if not token: return
    try:
        requests.put(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records/{record_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"fields": {"AI规划路线": url, "预计到达时间": eta}}
        )
    except:
        pass

# ===================== 发送司机卡片 =====================
def send_card(uid, order):
    token = get_lark_token()
    if not token or not uid: return
    try:
        requests.post(
            "https://open.larksuite.com/open-apis/im/v1/messages",
            params={"receive_id_type": "user_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": uid,
                "msg_type": "text",
                "content": json.dumps({"text": f"🚚 新订单\n地址：{order['address']}"})
            }
        )
    except:
        pass

# ===================== 唯一接口 =====================
@app.post("/lark-webhook")
async def webhook(request: Request):
    try:
        order = await request.json()
        driver = route_single(order)
        if not driver:
            return {"code":500,"msg":"规划失败"}

        map_url = driver.get("google_map_url", "")
        for stop in driver.get("route", []):
            if stop["type"] == "VISIT":
                update(order.get("record_id"), map_url, stop.get("arrival_time"))
                send_card(order.get("driver_user_id"), order)

        return {"code":200,"msg":"✅ 完成"}

    except Exception as e:
        send_alert("🚨 失败", str(e))
        return {"code":500,"msg":str(e)}

@app.get("/")
def home():
    return {"status":"ok","token_present":bool(ROUTIFIC_API_TOKEN)}
