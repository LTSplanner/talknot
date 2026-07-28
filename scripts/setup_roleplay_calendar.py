"""各対象者のカレンダーに「KNOTEロープレ（5分）」の固定枠を作る（冪等・DWD）。

平日13:00 開始・5分・毎週(月〜金)の繰り返し予定を、TARGET_ACCOUNTS それぞれの
プライマリカレンダーへ作成する。ドメイン全体委任（DWD）のサービスアカウントで
各人を subject に impersonate する。

冪等キー: ``extendedProperties.private.knote_roleplay = "1"``。
  既存の同キー予定があれば時刻/繰り返しを更新し、無ければ新規作成する。
  （同じ予定を二重に作らない）

認証:
  - GOOGLE_SERVICE_ACCOUNT_FILE（鍵ファイルのパス）か CALENDAR_SA_JSON（鍵JSON文字列）。
  - スコープ: https://www.googleapis.com/auth/calendar.events
実行:
  python scripts/setup_roleplay_calendar.py            # 実際に作成/更新
  python scripts/setup_roleplay_calendar.py --dry-run  # 作らず対象と内容だけ表示
時刻は env ROLEPLAY_SLOT_HHMM（既定 "13:00"）で変更可。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

from config import settings

# ライブ送信・書込に使うスコープ（events の作成/更新）。
_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_APP_URL = "https://talknot-lts.streamlit.app"
_IDEMPOTENT_KEY = "knote_roleplay"  # extendedProperties.private のキー
_TZ = "Asia/Tokyo"


def _slot_hhmm() -> tuple[int, int]:
    """ROLEPLAY_SLOT_HHMM（"HH:MM"）を (hour, minute) に。既定 13:00。"""
    raw = (os.getenv("ROLEPLAY_SLOT_HHMM") or "13:00").strip()
    try:
        h, m = raw.split(":")
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except (ValueError, AttributeError):
        return 13, 0


def _next_weekday(base: _dt.date) -> _dt.date:
    """base 当日を含め、次の平日（月〜金）を返す。"""
    d = base
    while d.weekday() >= 5:  # 5=土, 6=日
        d += _dt.timedelta(days=1)
    return d


def _event_body() -> dict:
    """作成/更新する予定の本体を組み立てる。"""
    hour, minute = _slot_hhmm()
    # 繰り返しの初回日。JST の「今日」以降で最初の平日を開始日にする。
    jst_today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).date()
    start_date = _next_weekday(jst_today)
    start = _dt.datetime(start_date.year, start_date.month, start_date.day, hour, minute)
    end = start + _dt.timedelta(minutes=5)
    return {
        "summary": "KNOTEロープレ（5分）",
        "description": (
            "1日5分、KNOTEでロープレを1本。短くてOK、続けることが力になります。\n"
            f"{_APP_URL}"
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": _TZ},
        "end": {"dateTime": end.isoformat(), "timeZone": _TZ},
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"],
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 0},
        ]},
        "extendedProperties": {"private": {_IDEMPOTENT_KEY: "1"}},
    }


def _credentials(subject: str):
    from google.oauth2 import service_account

    sa_json = (os.getenv("CALENDAR_SA_JSON") or "").strip()
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=_CALENDAR_SCOPES
        )
    else:
        path = (settings.GOOGLE_SERVICE_ACCOUNT_FILE or "").strip()
        if not path:
            raise RuntimeError("SA鍵が未設定（GOOGLE_SERVICE_ACCOUNT_FILE / CALENDAR_SA_JSON）")
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=_CALENDAR_SCOPES
        )
    return creds.with_subject(subject)


def _find_existing(service) -> dict | None:
    """冪等キーを持つ既存予定を1件返す（無ければ None）。"""
    resp = (
        service.events()
        .list(
            calendarId="primary",
            privateExtendedProperty=f"{_IDEMPOTENT_KEY}=1",
            maxResults=5,
            showDeleted=False,
        )
        .execute()
    )
    items = resp.get("items", [])
    return items[0] if items else None


def _upsert_for(email: str, body: dict, dry_run: bool) -> str:
    """1人分の予定を作成 or 更新。処理内容の説明文字列を返す。"""
    if dry_run:
        return "既存確認→作成/更新（dry-run のため未実行）"

    from googleapiclient.discovery import build

    creds = _credentials(subject=email)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    existing = _find_existing(service)
    if existing:
        service.events().update(
            calendarId="primary", eventId=existing["id"], body=body
        ).execute()
        return f"更新（eventId={existing['id']}）"
    created = service.events().insert(calendarId="primary", body=body).execute()
    return f"作成（eventId={created.get('id', '?')}）"


def main() -> int:
    parser = argparse.ArgumentParser(description="KNOTEロープレの固定枠を作成/更新")
    parser.add_argument("--dry-run", action="store_true", help="作成せず対象と内容を表示")
    args = parser.parse_args()

    targets = settings.TARGET_ACCOUNTS
    hour, minute = _slot_hhmm()
    body = _event_body()
    print(f"対象 {len(targets)} 名 / 枠 平日 {hour:02d}:{minute:02d} 開始・5分・毎週(月〜金)")
    print(f"タイトル: {body['summary']} / 冪等キー: {_IDEMPOTENT_KEY}=1")
    if args.dry_run:
        print("[dry-run] 実際の作成/更新は行いません。")

    ok, ng = 0, 0
    for email in targets:
        try:
            msg = _upsert_for(email, body, args.dry_run)
            print(f"  - {email}: {msg}")
            ok += 1
        except Exception as e:  # noqa: BLE001 1人失敗でも続行
            print(f"  - {email}: 失敗 {str(e)[:160]}")
            ng += 1
    print(f"完了: 成功 {ok} / 失敗 {ng}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
