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
import datetime as _dt
import hashlib
import json
import os
import sys

from config import settings
from core import badges, reminders
from services import google_calendar, google_chat, sheets_knowledge

_APP_URL = "https://talknot-lts.streamlit.app"


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
            off = reminders.is_off_today(events)
        except Exception as e:  # noqa: BLE001 取得失敗は通常送信に倒す
            print(f"  休み判定に失敗（通常どおり送信）: {email}: {str(e)[:120]}")
            off = False
        (dayoff if off else to_send).append(email)
    return to_send, dayoff


def _display_names(emails: list[str], sa_info: dict | None) -> dict[str, str]:
    """Workspace の表示名（例「熊田遥輝」）をまとめて引く。

    DWD の SA で本人になりすまし、Drive の about.get から氏名を取る。
    Directory API と違い管理者権限が要らず、既存のスコープだけで動く。
    取れなかった人は空文字にして、呼び出し側でメールのローカル部に戻す。
    """
    names: dict[str, str] = {}
    if not sa_info:
        return names

    from google.oauth2 import service_account

    from services import google_drive

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    for email in emails:
        try:
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=scopes).with_subject(email)
            names[email] = google_drive.get_display_name(creds)
        except Exception:  # noqa: BLE001 取れない人だけ諦める
            names[email] = ""
    return names


def _name_of(email: str, display_names: dict[str, str] | None = None) -> str:
    """呼びかけに使う名前。表示名が取れていればそれ、無ければメールのローカル部。"""
    name = (display_names or {}).get(email, "")
    return name or (email or "").split("@", 1)[0]


# リマインド本文の型。毎日続けてもらうのが目的なので、どれも次の順で組み立てる：
#   1. まず圧を外す（うまくやらなくていい）— 質を求められると手が止まるため
#   2. 所要時間を見せる（5分）— 先延ばしの言い訳を減らす
#   3. 毎日やる理由を、命令ではなく事実として置く
#   4. 迷わせずに行動へ
# 同じ文面が続くと読み飛ばされるので、人ごと・日ごとに切り替える（_variant_index）。
_MESSAGES = [
    "🎙️ {name}さん、今日の1本がまだ残っています。\n\n"
    "うまくやらなくて大丈夫です。5分で終わります。\n"
    "まとめてやるより、毎日ちいさく積むほうが確実に効きます。\n\n"
    "今日のぶん、いきましょう。",

    "🎙️ {name}さん、今日のロープレはこれからですね。\n\n"
    "気合いは要りません。5分だけ、いつもの1本を。\n"
    "毎日の1本が、来週の商談をかるくします。",

    "🎙️ {name}さん、まだ今日の1本が空いています。\n\n"
    "完璧じゃなくていいので、口を動かすところまで。\n"
    "続けている人ほど、本番でことばが出てきます。",

    "🎙️ {name}さん、今日はもうロープレしましたか？\n\n"
    "5分で終わります。うまくいかなくても、それが練習です。\n"
    "1日空けると戻すのに時間がかかります。今日のうちに。",

    "🎙️ {name}さん、今日の練習がまだですね。\n\n"
    "思い出すだけでも意味があります。まずは1本。\n"
    "毎日ふれているかどうかで、半年後が変わります。",

    "🎙️ {name}さん、5分あれば今日の1本が終わります。\n\n"
    "出来ばえは気にしなくて大丈夫。\n"
    "毎日つづけた人から、商談が変わっていきます。",

    "🎙️ {name}さん、今日のロープレ、まだ空いています。\n\n"
    "気が乗らない日ほど、短くていいので触れておくのがコツです。\n"
    "1本だけ、いきましょう。",

    "🎙️ {name}さん、今日のぶんがまだです。\n\n"
    "うまく話せなくて大丈夫。練習はそのためにあります。\n"
    "毎日の積み重ねが、いちばん早い近道です。",

    "🎙️ {name}さん、まだ今日の1本が残っています。\n\n"
    "完成度より、毎日ふれること。5分で足ります。\n"
    "今日も1本、いきましょう。",

    "🎙️ {name}さん、今日のロープレはこれからですか？\n\n"
    "ことばに詰まっても大丈夫です。詰まったところが伸びしろです。\n"
    "毎日1本、続けていきましょう。",

    "🎙️ {name}さん、今日の1本、まだですね。\n\n"
    "今日はうまくいかなくてもいい日です。声に出すところまでで十分。\n"
    "毎日やっている人ほど、本番で慌てません。",

    "🎙️ {name}さん、あと5分だけ時間をつくれますか。\n\n"
    "今日の1本を置いておくと、明日はもっと重くなります。\n"
    "軽いうちに、今日のうちに。",
]


def _variant_index(email: str, today: str) -> int:
    """その人・その日に使う文面の番号。

    「日付の通し番号 ＋ 人ごとのずらし幅」を文面数で割った余り。こうすると：
      - 同じ人が2日つづけて同じ文面を受け取らない（毎日1つずつ進む）
      - 同じ日でも人によって文面が違う（ずらし幅が人ごとに違う）
      - 何度実行しても同じ結果（再送しても文面が変わらない）
    """
    try:
        day_no = _dt.date.fromisoformat(today).toordinal()
    except ValueError:
        day_no = 0
    # Python の hash() は実行ごとに変わるため、安定するハッシュを使う。
    offset = int(hashlib.md5(email.encode("utf-8")).hexdigest(), 16)
    return (day_no + offset) % len(_MESSAGES)


def _streak_line(streak: int) -> str:
    """「今日やれば◯日連続」の一行。記録が途切れている人には出さない。

    0日の人に「今日やれば1日連続」と言っても意味が無く、むしろ途切れた事実を
    突きつけることになるので、続いている人にだけ添える。
    """
    if streak < 1:
        return ""
    return f"\n\n🔥 今日やれば {streak + 1} 日つづけて達成です。"


def _message_for(
    email: str, display_names: dict[str, str] | None = None, today: str = "",
    streak: int = 0,
) -> str:
    """その人・その日のリマインド本文（＋連続記録＋アプリURL）。"""
    body = _MESSAGES[_variant_index(email, today)]
    return (f"{body.format(name=_name_of(email, display_names))}"
            f"{_streak_line(streak)}\n{_APP_URL}")


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

    # 休みスキップ：カレンダーSAが使えるなら、その日が終日休みの人を送信対象から外す。
    # SA未設定・取得失敗時は「その人は通常どおり送る」（安全側）。
    dayoff: list[str] = []
    sa_info: dict | None = None
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

    # 「s.kageyamaさん」ではなく「景山冴香さん」と呼びかける（表示名が取れた人だけ）。
    names = _display_names(missed, sa_info)
    # 「今日やれば◯日連続」を添えるため、今つながっている連続日数を人ごとに出す。
    streaks = {
        email: badges.current_day_streak(
            [r for r in records if r.get("user_email") == email], "roleplay", today)
        for email in missed
    }
    email_to_text = {
        email: _message_for(email, names, today, streaks.get(email, 0))
        for email in missed
    }

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
