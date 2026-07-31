"""対象プランナー全員のKNOTE個別DMが準備済みか確認する（送信なし）。"""
from __future__ import annotations

import sys

from config import settings
from services import google_chat


def main() -> int:
    targets = settings.TARGET_ACCOUNTS
    print(f"個別DM準備確認 / 対象 {len(targets)} 名")
    if not google_chat.dm_configured():
        print("個人DM設定が未登録（CHAT_SA_* / CHAT_ADMIN_SUBJECT）。")
        return 1

    ready, missing, failed = [], [], []
    for email in targets:
        try:
            if google_chat.direct_message_exists(email):
                ready.append(email)
                print(f"  準備済み: {email}")
            else:
                missing.append(email)
                print(f"  未準備: {email}")
        except Exception as e:  # noqa: BLE001 1人失敗でも全員確認を続ける
            failed.append(email)
            print(f"  確認失敗: {email}: {str(e)[:160]}")

    print(
        f"結果: 準備済み {len(ready)} / 未準備 {len(missing)}"
        f" / 確認失敗 {len(failed)}"
    )
    return 0 if len(ready) == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
