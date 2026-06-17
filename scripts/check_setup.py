"""TalKnot セットアップ確認スクリプト。

`.env` の設定状況を点検し、Gemini API キーが有効かを軽いリクエストで確認する。

    python3 scripts/check_setup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def _mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def main() -> int:
    print("=== TalKnot セットアップ確認 ===\n")

    print("[アクセス制御]")
    print(f"  許可ドメイン : {settings.ALLOWED_DOMAINS}")
    print(f"  管理者       : {settings.ADMIN_EMAILS or '(未設定)'}")

    print("\n[Google OAuth]")
    has_oauth = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    print(f"  {_mark(bool(settings.GOOGLE_CLIENT_ID))} GOOGLE_CLIENT_ID")
    print(f"  {_mark(bool(settings.GOOGLE_CLIENT_SECRET))} GOOGLE_CLIENT_SECRET")
    print(f"  リダイレクトURI : {settings.OAUTH_REDIRECT_URI}")
    if not has_oauth:
        print("  → 未設定の場合、アプリはデモログインで起動します（Drive連携は不可）。")

    print("\n[Gemini]")
    print(f"  モデル : {settings.GEMINI_MODEL}")
    if not settings.GEMINI_API_KEY:
        print(f"  {_mark(False)} GEMINI_API_KEY が未設定です。")
        return 1

    print(f"  {_mark(True)} GEMINI_API_KEY あり。接続テスト中…")
    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents="「TalKnotの準備完了」とだけ返答してください。",
        )
        print(f"  {_mark(True)} 接続成功。応答: {resp.text.strip()[:60]}")
    except Exception as e:
        print(f"  {_mark(False)} 接続失敗: {e}")
        return 1

    print("\nすべて確認できました。`streamlit run app.py` で起動できます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
