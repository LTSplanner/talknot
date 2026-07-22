"""Google カレンダー連携：商談（Meet）予定の一覧と、その録画の突き合わせ。

- ログイン中ユーザーの OAuth Credentials（calendar.readonly / drive.readonly）で動く。
- Meet で行った商談は、録画がオーガナイザーのドライブに残る設計を前提とする。
  カレンダーの予定タイトルと録画ファイル名（＝会議名＋日時）を突き合わせて紐づける。
"""
from __future__ import annotations

import datetime as _dt
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from services import google_drive


def _service(credentials: Credentials):
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _norm(text: str) -> str:
    return re.sub(r"[\s　・|｜／/,、。]+", "", (text or "")).lower()


def list_meetings(
    credentials: Credentials, days_back: int = 60, days_ahead: int = 1
) -> list[dict]:
    """直近の『Meet付き予定（＝オンライン商談）』を新しい順で返す。

    各要素: {id, summary, start, start_date, has_meet}
    """
    service = _service(credentials)
    now = _dt.datetime.now(_dt.timezone.utc)
    time_min = (now - _dt.timedelta(days=days_back)).isoformat()
    time_max = (now + _dt.timedelta(days=days_ahead)).isoformat()

    resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    out: list[dict] = []
    for ev in resp.get("items", []):
        start = ev.get("start", {})
        start_raw = start.get("dateTime") or start.get("date") or ""
        has_meet = bool(
            ev.get("hangoutLink")
            or (ev.get("conferenceData", {}).get("conferenceId"))
        )
        out.append({
            "id": ev.get("id", ""),
            "summary": ev.get("summary", "（無題）"),
            "start": start_raw,
            "start_date": start_raw[:10],
            "has_meet": has_meet,
        })
    out.sort(key=lambda e: e.get("start", ""), reverse=True)
    return out


def find_recording(
    credentials: Credentials, summary: str, start_date: str
) -> dict | None:
    """予定タイトル・日付に一致する録画（自分のドライブ内）を1件返す。無ければ None。

    照合の優先度：
      1) タイトル内の案件ID（L########）が録画名に含まれる（最も確実）
      2) タイトルの主要トークンが録画名に多く含まれる ＋ 作成日が近い
    """
    videos = google_drive.list_videos(credentials, owned_only=True)
    if not videos:
        return None

    id_match = re.search(r"[LＬ]\s*\d{6,}", summary or "")
    key_id = re.sub(r"\s", "", id_match.group()) if id_match else None

    def score(v: dict) -> float:
        name = v.get("name", "")
        n_name, n_sum = _norm(name), _norm(summary)
        s = 0.0
        if key_id and _norm(key_id) in n_name:
            s += 100
        # タイトルの連続部分一致（顧客名・物件名など）
        if n_sum:
            longest = 0
            for i in range(len(n_sum)):
                for j in range(i + 4, len(n_sum) + 1):
                    if n_sum[i:j] in n_name and (j - i) > longest:
                        longest = j - i
            s += longest
        # 日付の近さ（±2日以内を加点）
        created = v.get("createdTime", "")[:10]
        if created and start_date:
            try:
                d = abs((_dt.date.fromisoformat(created) - _dt.date.fromisoformat(start_date)).days)
                if d <= 2:
                    s += 8 - d * 2
            except ValueError:
                pass
        return s

    best = max(videos, key=score)
    return best if score(best) >= 6 else None
