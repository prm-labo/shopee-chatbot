import hmac
import hashlib
import time
import os
import httpx
from database import update_tokens

PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "0"))
PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "")
REDIRECT_URL = os.getenv("SHOPEE_REDIRECT_URL", "")
BASE_URL = "https://partner.shopeemobile.com/api/v2"


def _sign(api_path: str, timestamp: int, access_token: str = "", shop_id: int = 0) -> str:
    base = f"{PARTNER_ID}{api_path}{timestamp}"
    if access_token:
        base += f"{access_token}{shop_id}"
    return hmac.new(PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()


def _params(api_path: str, access_token: str = "", shop_id: int = 0) -> dict:
    ts = int(time.time())
    return {
        "partner_id": PARTNER_ID,
        "timestamp": ts,
        "sign": _sign(api_path, ts, access_token, shop_id),
        **({"access_token": access_token, "shop_id": shop_id} if access_token else {}),
    }


def get_auth_url() -> str:
    path = "/api/v2/shop/auth_partner"
    ts = int(time.time())
    sign = _sign(path, ts)
    return (
        f"https://partner.shopeemobile.com/api/v2/shop/auth_partner"
        f"?partner_id={PARTNER_ID}&timestamp={ts}&sign={sign}&redirect={REDIRECT_URL}"
    )


async def exchange_code_for_token(code: str, shop_id: int) -> dict:
    path = "/api/v2/auth/token/get"
    ts = int(time.time())
    sign = _sign(path, ts)
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{BASE_URL}/auth/token/get",
            params={"partner_id": PARTNER_ID, "timestamp": ts, "sign": sign},
            json={"code": code, "shop_id": shop_id, "partner_id": PARTNER_ID},
        )
    data = res.json()
    expires_at = int(time.time()) + data.get("expire_in", 14400)
    update_tokens(shop_id, data["access_token"], data["refresh_token"], expires_at)
    return data


async def refresh_token(shop_id: int, refresh_token_val: str) -> dict:
    path = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    sign = _sign(path, ts)
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{BASE_URL}/auth/access_token/get",
            params={"partner_id": PARTNER_ID, "timestamp": ts, "sign": sign},
            json={"refresh_token": refresh_token_val, "shop_id": shop_id, "partner_id": PARTNER_ID},
        )
    data = res.json()
    expires_at = int(time.time()) + data.get("expire_in", 14400)
    update_tokens(shop_id, data["access_token"], data["refresh_token"], expires_at)
    return data


async def _ensure_token(user: dict) -> str:
    if int(time.time()) >= user["token_expires_at"] - 300:
        data = await refresh_token(user["shop_id"], user["refresh_token"])
        return data["access_token"]
    return user["access_token"]


async def get_conversation_list(user: dict) -> list:
    token = await _ensure_token(user)
    path = "/api/v2/sellerchat/get_conversation_list"
    params = _params(path, token, user["shop_id"])
    params.update({"page_size": 25, "filter": "all"})
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/sellerchat/get_conversation_list", params=params)
    return res.json().get("response", {}).get("conversations", [])


async def get_messages(user: dict, conversation_id: str) -> list:
    token = await _ensure_token(user)
    path = "/api/v2/sellerchat/get_message"
    params = _params(path, token, user["shop_id"])
    params.update({"conversation_id": conversation_id, "page_size": 10})
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/sellerchat/get_message", params=params)
    return res.json().get("response", {}).get("messages", [])


async def send_message(user: dict, to_id: int, message: str) -> bool:
    token = await _ensure_token(user)
    path = "/api/v2/sellerchat/send_message"
    params = _params(path, token, user["shop_id"])
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{BASE_URL}/sellerchat/send_message",
            params=params,
            json={
                "to_id": to_id,
                "message_type": "text",
                "content": {"text": message},
            },
        )
    result = res.json()
    print(f"[send_message] to_id={to_id} error={result.get('error')} message={result.get('message')}")
    return result.get("error") == ""


async def get_products(user: dict) -> list:
    token = await _ensure_token(user)
    path = "/api/v2/product/get_item_list"
    params = _params(path, token, user["shop_id"])
    params.update({"offset": 0, "page_size": 100, "item_status": "NORMAL"})
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{BASE_URL}/product/get_item_list", params=params)
    items = res.json().get("response", {}).get("item", [])

    if not items:
        return []

    item_ids = [str(i["item_id"]) for i in items]
    path2 = "/api/v2/product/get_item_base_info"
    params2 = _params(path2, token, user["shop_id"])
    params2["item_id_list"] = ",".join(item_ids)
    async with httpx.AsyncClient() as client:
        res2 = await client.get(f"{BASE_URL}/product/get_item_base_info", params=params2)
    return res2.json().get("response", {}).get("item_list", [])
