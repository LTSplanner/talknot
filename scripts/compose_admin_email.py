"""管理者への依頼メールを、Gmailの「新規作成」画面に入力済みで開く。

宛先・件名・本文を埋めた Gmail 作成URLをブラウザで開くだけ。送信はしない
（内容を確認して自分で送信する）。

    python3 scripts/compose_admin_email.py
"""
from __future__ import annotations

import urllib.parse
import webbrowser
from pathlib import Path

TO = "ryouchiku@life-time-support.com"
CC = "planner@life-time-support.com"
SUBJECT = "【ご依頼】TalKnot 用 Drive 代理アクセス設定のお願い"
BODY_FILE = Path(__file__).resolve().parent.parent / "docs" / "管理者への依頼.md"


def main() -> int:
    body = BODY_FILE.read_text(encoding="utf-8")
    params = urllib.parse.urlencode(
        {"view": "cm", "fs": "1", "to": TO, "cc": CC, "su": SUBJECT, "body": body},
        quote_via=urllib.parse.quote,
    )
    url = f"https://mail.google.com/mail/?{params}"
    print("Gmail の作成画面を開きます（送信はされません。内容を確認して送信してください）。")
    print(f"宛先: {TO} / CC: {CC}")
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
