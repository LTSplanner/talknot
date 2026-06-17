"""ドメイン全体委任（DWD）の動作確認。

各対象メンバー（settings.TARGET_ACCOUNTS）になりすまして、ドライブの
動画件数を取得できるか点検する。

    python3 scripts/check_drive_delegation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import drive_sa, google_drive  # noqa: E402


def main() -> int:
    print("=== ドメイン全体委任（DWD）確認 ===\n")
    if not drive_sa.configured():
        print("❌ GOOGLE_SERVICE_ACCOUNT_FILE が未設定、または鍵ファイルが見つかりません。")
        print("   docs/SETUP_SERVICE_ACCOUNT.md の手順 A / C を確認してください。")
        return 1

    print(f"鍵ファイル: {settings.GOOGLE_SERVICE_ACCOUNT_FILE}")
    print(f"模範アカウント: {', '.join(settings.REFERENCE_ACCOUNTS)}\n")

    ok = 0
    for email in settings.TARGET_ACCOUNTS:
        try:
            creds = drive_sa.impersonate(email)
            videos = google_drive.list_videos(creds)
            mark = "⭐" if email in settings.REFERENCE_ACCOUNTS else "  "
            print(f"  ✅ {mark} {email}: 動画 {len(videos)} 件")
            ok += 1
        except Exception as e:
            print(f"  ❌    {email}: {e}")

    print(f"\n成功 {ok}/{len(settings.TARGET_ACCOUNTS)} アカウント")
    if ok < len(settings.TARGET_ACCOUNTS):
        print("失敗がある場合は Admin Console の委任（クライアントID/スコープ）を見直してください。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
