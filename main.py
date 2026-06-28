import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from database import init_db, get_all_active_users, add_user
from shopee_client import get_auth_url, exchange_code_for_token
from bot_engine import process_shop_messages
from line_client import handle_webhook

scheduler = AsyncIOScheduler()


async def poll_all_shops():
    users = get_all_active_users()
    for user in users:
        await process_shop_messages(dict(user))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(poll_all_shops, "interval", seconds=60, id="poll")
    scheduler.start()
    print("[Server] 起動完了 - ポーリング間隔: 60秒")
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Shopee チャットボット</title>
      <style>
        body { font-family: sans-serif; max-width: 600px; margin: 60px auto; padding: 0 20px; }
        h1 { color: #ee4d2d; }
        .btn {
          display: inline-block; background: #ee4d2d; color: white;
          padding: 14px 28px; border-radius: 8px; text-decoration: none;
          font-size: 16px; margin-top: 20px;
        }
        .step { background: #f5f5f5; padding: 16px; border-radius: 8px; margin: 12px 0; }
      </style>
    </head>
    <body>
      <h1>Shopee チャットボット</h1>
      <p>Shopeeのチャットに自動返信するボットです。以下の手順で設定してください。</p>

      <div class="step"><strong>Step 1</strong>：下のボタンをクリックしてShopeeアカウントを連携</div>
      <div class="step"><strong>Step 2</strong>：連携後に表示されるコードをLINEボットに送信</div>
      <div class="step"><strong>Step 3</strong>：設定完了！自動返信が開始されます</div>

      <a href="/auth/shopee" class="btn">Shopeeアカウントを連携する</a>
    </body>
    </html>
    """


@app.get("/auth/shopee")
async def shopee_auth():
    return RedirectResponse(get_auth_url())


@app.get("/auth/shopee/callback", response_class=HTMLResponse)
async def shopee_callback(code: str, shop_id: int):
    try:
        data = await exchange_code_for_token(code, shop_id)
        import time
        expires_at = int(time.time()) + data.get("expire_in", 14400)
        reg_token = add_user(
            shop_id=shop_id,
            shop_name=str(shop_id),
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at,
        )

        line_bot_url = f"https://line.me/R/oaMessage/@{os.getenv('LINE_BOT_ID', 'YOUR_BOT_ID')}/?{reg_token}"

        return f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
          <meta charset="UTF-8">
          <title>連携完了</title>
          <style>
            body {{ font-family: sans-serif; max-width: 600px; margin: 60px auto; padding: 0 20px; }}
            h1 {{ color: #27ae60; }}
            .code {{ background: #f0f0f0; padding: 20px; font-size: 24px; font-weight: bold;
                     text-align: center; border-radius: 8px; letter-spacing: 4px; margin: 20px 0; }}
            .btn {{ display: inline-block; background: #06c755; color: white;
                    padding: 14px 28px; border-radius: 8px; text-decoration: none; font-size: 16px; }}
          </style>
        </head>
        <body>
          <h1>✅ Shopee連携完了！</h1>
          <p><strong>次のステップ：</strong>LINEボットに以下のコードを送信してください。</p>
          <div class="code">{reg_token}</div>
          <p>または下のボタンからLINEボットを開いてコードを送信：</p>
          <a href="{line_bot_url}" class="btn">LINEボットを開く</a>
        </body>
        </html>
        """
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"連携エラー: {e}")


@app.post("/webhook/line")
async def line_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    await handle_webhook(body, signature)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
