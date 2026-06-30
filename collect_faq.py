"""
FAQ自動収集スクリプト
使い方：Shopeeの6ショップのOAuth認証完了後に実行
実行コマンド：python collect_faq.py
"""
import asyncio
import json
import os
import gspread
from google.oauth2.service_account import Credentials
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
import httpx
import hmac
import hashlib
import time

load_dotenv()

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "0"))
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
BASE_URL = "https://partner.shopeemobile.com/api/v2"

claude = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _sign(api_path, timestamp, access_token="", shop_id=0):
    base = f"{PARTNER_ID}{api_path}{timestamp}"
    if access_token:
        base += f"{access_token}{shop_id}"
    return hmac.new(PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()


def _params(api_path, access_token="", shop_id=0):
    ts = int(time.time())
    return {
        "partner_id": PARTNER_ID,
        "timestamp": ts,
        "sign": _sign(api_path, ts, access_token, shop_id),
        **({"access_token": access_token, "shop_id": shop_id} if access_token else {}),
    }


async def fetch_conversations(shop_id: int, access_token: str) -> list:
    path = "/api/v2/sellerchat/get_conversation_list"
    params = _params(path, access_token, shop_id)
    params.update({"page_size": 50, "filter": "all"})
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/sellerchat/get_conversation_list", params=params)
    return res.json().get("response", {}).get("conversations", [])


async def fetch_messages(shop_id: int, access_token: str, conversation_id: str) -> list:
    path = "/api/v2/sellerchat/get_message"
    params = _params(path, access_token, shop_id)
    params.update({"conversation_id": conversation_id, "page_size": 50})
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/sellerchat/get_message", params=params)
    return res.json().get("response", {}).get("messages", [])


async def extract_qa_pairs(conversation_text: str) -> list[dict]:
    if not conversation_text.strip():
        return []

    message = await claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system="""会話履歴からFAQのQ&Aペアを抽出してください。
購入者の質問とセラーの回答のペアのみを抽出します。
必ずJSON配列で返してください：
[{"質問": "...", "回答": "..."}, ...]
抽出できない場合は空配列 [] を返してください。""",
        messages=[{"role": "user", "content": f"以下の会話からQ&Aを抽出してください：\n\n{conversation_text}"}],
    )

    text = message.content[0].text.strip()
    try:
        start = text.find("[")
        end = text.rfind("]") + 1
        return json.loads(text[start:end]) if start != -1 else []
    except Exception:
        return []


def get_sheets_client():
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    creds_dict = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def write_to_sheets(qa_pairs: list[dict]):
    gc = get_sheets_client()
    sh = gc.open_by_key(SHEETS_ID)
    ws = sh.sheet1

    existing = ws.get_all_values()
    existing_questions = {row[0] for row in existing[1:] if row}

    new_rows = []
    for qa in qa_pairs:
        q = qa.get("質問", "").strip()
        a = qa.get("回答", "").strip()
        if q and a and q not in existing_questions:
            new_rows.append([q, a])
            existing_questions.add(q)

    if new_rows:
        ws.append_rows(new_rows)
        print(f"[Sheets] {len(new_rows)}件のQ&Aを追加しました")
    else:
        print("[Sheets] 新規Q&Aなし（重複スキップ）")


async def collect_from_shop(shop_id: int, access_token: str):
    print(f"\n[Shop {shop_id}] チャット履歴を取得中...")
    conversations = await fetch_conversations(shop_id, access_token)
    print(f"[Shop {shop_id}] {len(conversations)}件の会話を取得")

    all_qa = []
    for conv in conversations:
        conv_id = conv.get("conversation_id")
        if not conv_id:
            continue

        messages = await fetch_messages(shop_id, access_token, conv_id)

        lines = []
        for msg in messages:
            if msg.get("message_type") != "text":
                continue
            from_id = str(msg.get("from_user_id", ""))
            text = msg.get("content", {}).get("text", "").strip()
            if not text:
                continue
            role = "セラー" if from_id == str(shop_id) else "購入者"
            lines.append(f"{role}：{text}")

        if lines:
            qa_pairs = await extract_qa_pairs("\n".join(lines))
            all_qa.extend(qa_pairs)

    print(f"[Shop {shop_id}] {len(all_qa)}件のQ&Aを抽出")
    return all_qa


async def main():
    from database import init_db, get_all_active_users
    init_db()
    users = get_all_active_users()

    if not users:
        print("認証済みショップがありません。先にOAuth連携を完了してください。")
        return

    all_qa = []
    for user in users:
        qa = await collect_from_shop(user["shop_id"], user["access_token"])
        all_qa.extend(qa)

    print(f"\n合計 {len(all_qa)} 件のQ&Aを収集しました")

    if all_qa:
        write_to_sheets(all_qa)
        print("Google Sheetsへの書き込み完了")


if __name__ == "__main__":
    asyncio.run(main())
