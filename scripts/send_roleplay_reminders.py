"""午前中ロープレ未実施の対象者へ、前向きなリマインドを送る（平日12:00・JST）。

流れ:
  1. sheets_knowledge.load_evaluations() で評価レコードを読む。
  2. core.reminders.missed_before() で午前中ロープレ未実施の対象者を出す。
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
import json
import os
import sys

from config import settings
from core import reminders
from services import google_calendar, google_chat, sheets_knowledge

_APP_URL = "https://talknot-lts.streamlit.app"
_MORNING_CUTOFF = "12:00:00"


def _calendar_sa_info() -> dict | None:
    """休みチェック用のカレンダーSA情報（鍵JSONのdict）を env から読む。

    CALENDAR_SA_JSON（JSON文字列）を優先し、無ければ GOOGLE_SERVICE_ACCOUNT_FILE
    （鍵ファイルのパス）を使う。どちらも無効なら None（＝休みチェックはスキップ）。
    """
    raw = (os.getenv("CALENDAR_SA_JSON") or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    path = (settings.GOOGLE_SERVICE_ACCOUNT_FILE or "").strip()
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    return None


def _filter_out_dayoff(
    missed: list[str], today: str, sa_info: dict
) -> tuple[list[str], list[str]]:
    """未実施者から「その日が休みの人」を除いて (送る, スキップ) に分ける。

    カレンダー取得や判定で失敗した人は安全側（送る）に倒す。全員無送信を招かない。
    """
    to_send: list[str] = []
    dayoff: list[str] = []
    for email in missed:
        off = False
        try:
            events = google_calendar.list_events_on(today, email, sa_info)
            off = reminders.is_off_morning(events)
        except Exception as e:  # noqa: BLE001 取得失敗は通常送信に倒す
            print(f"  休み判定に失敗（通常どおり送信）: {email}: {str(e)[:120]}")
            off = False
        (dayoff if off else to_send).append(email)
    return to_send, dayoff


def _name_of(email: str) -> str:
    """メールのローカル部を表示名代わりに使う（氏名マスタが無いため）。"""
    return (email or "").split("@", 1)[0]


def _message_for(email: str) -> str:
    """前向き＆短いリマインド本文（＋アプリURL）。"""
    return (
        f"🎙️ {_name_of(email)}さん、午前中のKNOTEロープレがまだ完了していません。\n"
        "5分でOKです。午後のスタート前に、サッと1本いきましょう！\n"
        f"{_APP_URL}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="午前中ロープレ未実施者へリマインド")
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

    missed = reminders.missed_before(records, targets, today, _MORNING_CUTOFF)
    print(f"午前中ロープレ未実施: {len(missed)} 名")
    for email in missed:
        print(f"  - {email}")

    # 休みスキップ：カレンダーSAが使えるなら、その日が終日休みの人を送信対象から外す。
    # SA未設定・取得失敗時は「その人は通常どおり送る」（安全側）。
    dayoff: list[str] = []
    if missed:
        sa_info = _calendar_sa_info()
        if sa_info is None:
            print("カレンダーSA未設定（CALENDAR_SA_JSON / GOOGLE_SERVICE_ACCOUNT_FILE）。休み判定はスキップ（全員に送る）。")
        else:
            missed, dayoff = _filter_out_dayoff(missed, today, sa_info)
            print(f"うち休みでスキップ: {len(dayoff)} 名 / 実際に送る: {len(missed)} 名")
            for email in dayoff:
                print(f"  休みスキップ: {email}")

    if not missed:
        print("送る対象なし。リマインド不要。")
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
