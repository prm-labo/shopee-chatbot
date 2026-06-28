import time
import json
from database import (
    is_message_processed, mark_message_processed,
    update_product_cache, get_user_by_shop_id
)
from shopee_client import get_conversation_list, get_messages, send_message, get_products
from claude_client import generate_response
from sheets_client import get_school_faq
from line_client import send_notification

PRODUCT_CACHE_TTL = 86400  # 1日


def _build_product_text(products: list) -> str:
    lines = []
    for p in products:
        name = p.get("item_name", "")
        desc = p.get("description", "")[:200]
        price_info = p.get("price_info", [{}])
        price = price_info[0].get("current_price", 0) / 100000 if price_info else 0
        lines.append(f"商品名: {name}\n価格: {price:.0f}\n説明: {desc}")
    return "\n\n".join(lines[:30])  # 最大30商品


async def _refresh_product_cache(user: dict):
    now = int(time.time())
    updated_at = user["product_cache_updated_at"] or 0
    if now - updated_at < PRODUCT_CACHE_TTL and user["product_cache"]:
        return

    try:
        products = await get_products(user)
        product_text = _build_product_text(products)
        update_product_cache(user["shop_id"], product_text)
    except Exception as e:
        print(f"[Bot] 商品情報取得エラー shop_id={user['shop_id']}: {e}")


async def process_shop_messages(user: dict):
    shop_id = user["shop_id"]

    try:
        await _refresh_product_cache(user)
        user = get_user_by_shop_id(shop_id)  # キャッシュ更新後に再取得

        conversations = await get_conversation_list(user)
        school_faq = get_school_faq()
        product_data = user["product_cache"] or ""

        for conv in conversations:
            conv_id = conv.get("conversation_id")
            if not conv_id:
                continue

            messages = await get_messages(user, conv_id)

            for msg in messages:
                msg_id = str(msg.get("message_id", ""))
                msg_type = msg.get("message_type", "")
                from_user = msg.get("from_user_id")
                content = msg.get("content", {})

                if not msg_id or msg_type != "text":
                    continue

                if str(from_user) == str(shop_id):
                    continue  # 自分が送ったメッセージはスキップ

                if is_message_processed(shop_id, msg_id):
                    continue

                buyer_message = content.get("text", "").strip()
                if not buyer_message:
                    continue

                mark_message_processed(shop_id, msg_id)

                response, is_confident = await generate_response(
                    buyer_message, school_faq, product_data
                )

                if is_confident and response:
                    await send_message(user, conv_id, response)
                else:
                    if user["line_user_id"]:
                        notify_text = (
                            f"⚠️ 自動返信できないメッセージがあります\n\n"
                            f"購入者メッセージ:\n{buyer_message}\n\n"
                            f"Shopeeセラーセンターで直接ご返信ください。"
                        )
                        await send_notification(user["line_user_id"], notify_text)

    except Exception as e:
        print(f"[Bot] エラー shop_id={shop_id}: {e}")
