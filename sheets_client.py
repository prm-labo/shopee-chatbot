import os
import json
import time
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")

_faq_cache: str = ""
_cache_updated_at: int = 0
CACHE_TTL = 3600  # 1時間


def _get_client():
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    creds_dict = json.loads(service_account_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_school_faq() -> str:
    global _faq_cache, _cache_updated_at

    if _faq_cache and (time.time() - _cache_updated_at) < CACHE_TTL:
        return _faq_cache

    try:
        gc = _get_client()
        sh = gc.open_by_key(SHEETS_ID)
        ws = sh.sheet1
        rows = ws.get_all_values()

        if not rows:
            return ""

        lines = []
        for row in rows[1:]:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                lines.append(f"Q: {row[0].strip()}\nA: {row[1].strip()}")

        _faq_cache = "\n\n".join(lines)
        _cache_updated_at = int(time.time())
        return _faq_cache

    except Exception as e:
        print(f"[Sheets] FAQ取得エラー: {e}")
        return _faq_cache
