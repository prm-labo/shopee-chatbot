import os
import json
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """あなたはShopeeのセラーに代わって購入者の質問に答えるカスタマーサポートアシスタントです。

## ルール
1. 必ず提供されたFAQと商品情報のみを根拠に回答すること
2. FAQや商品情報に該当しない質問には絶対に推測で答えないこと
3. 購入者が書いた言語と同じ言語で回答すること（タイ語で来たらタイ語で、インドネシア語で来たらインドネシア語で）
4. 丁寧かつ簡潔に回答すること

## 出力形式（必ずJSONで返すこと）
{
  "response": "購入者への回答文（回答不能な場合は空文字）",
  "confidence": "high または low",
  "reason": "lowの場合のみ理由を記載"
}

confidence=lowにする条件：
- FAQにも商品情報にも該当する情報がない
- 質問が複数の意味に解釈でき、回答が不確か
- 在庫・配送状況など、リアルタイム情報が必要な質問"""


async def generate_response(
    buyer_message: str,
    school_faq: str,
    product_data: str,
) -> tuple[str, bool]:
    """Returns (response_text, is_confident)"""
    user_content = f"""## スクールFAQ
{school_faq}

## このショップの商品情報
{product_data if product_data else "（商品情報なし）"}

## 購入者からのメッセージ
{buyer_message}"""

    message = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    text = message.content[0].text.strip()

    try:
        data = json.loads(text)
        response = data.get("response", "")
        is_confident = data.get("confidence", "low") == "high"
        return response, is_confident
    except json.JSONDecodeError:
        return "", False
