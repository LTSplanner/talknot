"""当日ロープレ未実施の対象者へ、前向きなリマインドを送る（平日15:00・JST）。

流れ:
  1. sheets_knowledge.load_evaluations() で評価レコードを読む。
  2. core.reminders.missed_today() で当日ロープレ未実施の対象者を出す。
  3. services.google_chat.notify() で各人へDM（またはWebhookでまとめ投稿）。

方針:
  - 送信設定（Chat）や履歴設定（Knowledgeシート）が無い場合は送らず、
    警告を出して exit 0（CI/Actions を赤くしない）。
  - --dry-run では送信せず、対象と本文を表示するだけ。
  - どんな例外でもプロセスを落とさない（最後は exit 0）。

storage 実行 env: KNOWLEDGE_SHEET_ID, KNOWLEDGE_SA_JSON か KNOWLEDGE_SA_FILE。
送信 env（いずれか）: CHAT_SA_JSON/CHAT_SA_FILE + CHAT_ADMIN_SUBJECT、または CHAT_WEBHOOK_URL。
"""
from __future__ import annotations

import argparse
import sys

from config import settings
from core import reminders
from services import google_chat, sheets_knowledge

_APP_URL = "https://talknot-lts.streamlit.app"


def _name_of(email: str) -> str:
    """メールのローカル部を表示名代わりに使う（氏名マスタが無いため）。"""
    return (email or "").split("@", 1)[0]


def _message_for(email: str) -> str:
    """前向き＆短いリマインド本文（＋アプリURL）。"""
    return (
        f"🎙️ {_name_of(email)}さん、今日のロープレはまだ1本残っています。\n"
        "5分でOK、続けた分だけ商談が変わります。今からサッと1本いきましょう！\n"
        f"{_APP_URL}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="当日ロープレ未実施者へリマインド")
    parser.add_argument("--dry-run", action="store_true", help="送信せず対象と本文を表示")
    args = parser.parse_args()

    today = reminders.today_jst_str()
    targets = settings.TARGET_ACCOUNTS
    print(f"基準日(JST): {today} / 対象 {len(targets)} 名")

    # 履歴（評価レコード）の設定が無ければ、当日実施の判定ができないためスキップ。
    if not sheets_knowledge.configured():
        print("評価履歴シートが未設定（KNOWLEDGE_SHEET_ID / KNOWLEDGE_SA）。送信せず終了。")
        return 0

    try:
        records = sheets_knowledge.load_evaluations()
    except Exception as e:  # noqa: BLE001
        print("評価履歴の読み込みに失敗。送信せず終了:", str(e)[:160])
        return 0

    missed = reminders.missed_today(records, targets, today)
    print(f"当日ロープレ未実施: {len(missed)} 名")
    for email in missed:
        print(f"  - {email}")

    if not missed:
        print("全員実施済み。リマインド不要。")
        return 0

    email_to_text = {email: _message_for(email) for email in missed}

    if args.dry_run:
        print("[dry-run] 送信は行いません。本文プレビュー:")
        for email, text in email_to_text.items():
            print(f"--- to {email} ---")
            print(text)
        return 0

    if not google_chat.configured():
        print("Chat送信が未設定（CHAT_SA_* / CHAT_ADMIN_SUBJECT か CHAT_WEBHOOK_URL）。送信せず終了。")
        return 0

    result = google_chat.notify(email_to_text)
    if result.get("skipped"):
        print("送信経路なしのためスキップ。")
        return 0
    print(f"送信モード: {result.get('mode')} / 成功 {len(result.get('sent', []))} 件 "
          f"/ 失敗 {len(result.get('failed', []))} 件")
    for email, err in result.get("failed", []):
        print(f"  失敗: {email}: {err}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("想定外エラー（無視して終了）:", str(e)[:200])
        sys.exit(0)
