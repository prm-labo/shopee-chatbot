import os
import hmac
import hashlib
import base64
import json
import httpx
from database import link_line_user, get_user_by_registration_token

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_API = "https://api.line.me/v2/bot/message/push"


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode() == signature


async def send_notification(line_user_id: str, message: str):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": message}],
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(LINE_API, headers=headers, json=payload)
    if res.status_code != 200:
        print(f"[LINE] 送信エラー: {res.text}")


async def handle_webhook(body: bytes, signature: str):
    if not verify_signature(body, signature):
        return

    events = json.loads(body).get("events", [])
    for event in events:
        event_type = event.get("type")
        line_user_id = event.get("source", {}).get("userId")

        if event_type == "message" and event.get("message", {}).get("type") == "text":
            text = event["message"]["text"].strip()
            user = get_user_by_registration_token(text)
            if user and line_user_id:
                success = link_line_user(text, line_user_id)
                if success:
                    await send_notification(line_user_id, "✅ 連携完了！Shopeeチャットの自動返信が有効になりました。")
                else:
                    await send_notification(line_user_id, "このコードはすでに使用済みです。")
