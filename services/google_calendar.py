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


# 商談タイトルに必ず入る案件番号（例: L260721484101）。全角Ｌ・間の空白も許容。
# find_recording の照合と同じパターンを流用し、録画突き合わせと整合させる。
_CASE_ID_RE = re.compile(r"[LＬ]\s*\d{6,}")


def _case_id(summary: str) -> str | None:
    """タイトルから案件番号を抜き出す（空白除去して返す）。無ければ None。"""
    m = _CASE_ID_RE.search(summary or "")
    return re.sub(r"\s", "", m.group()) if m else None


def list_meetings(
    credentials: Credentials, days_back: int = 60, days_ahead: int = 1,
    deals_only: bool = True,
) -> list[dict]:
    """直近の予定を新しい順で返す。

    deals_only=True（既定）のときは、タイトルに案件番号（L＋6桁以上）を含む
    『商談』だけを返す（営業会議・テスト・交流会などの非商談は除外）。
    各要素: {id, summary, start, start_date, has_meet, case_id}
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
        summary = ev.get("summary", "（無題）")
        case_id = _case_id(summary)
        # 商談のみ表示：案件番号を持たない予定（会議・テスト等）は除外
        if deals_only and not case_id:
            continue
        start = ev.get("start", {})
        start_raw = start.get("dateTime") or start.get("date") or ""
        has_meet = bool(
            ev.get("hangoutLink")
            or (ev.get("conferenceData", {}).get("conferenceId"))
        )
        out.append({
            "id": ev.get("id", ""),
            "summary": summary,
            "start": start_raw,
            "start_date": start_raw[:10],
            "has_meet": has_meet,
            "case_id": case_id or "",
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

    def _date_rank(v: dict) -> int:
        """作成日が予定日に近いほど大きい値（候補の中の順位付け＝タイブレークにのみ使う）。"""
        created = v.get("createdTime", "")[:10]
        if created and start_date:
            try:
                d = abs((_dt.date.fromisoformat(created)
                         - _dt.date.fromisoformat(start_date)).days)
                return 10 - d
            except ValueError:
                pass
        return -100

    # 1) 案件番号（L########）での厳密照合を最優先。
    #    録画名に案件番号が無ければ、別のお客様の録画を誤って掴まないよう None を返す。
    id_match = re.search(r"[LＬ]\s*\d{6,}", summary or "")
    key_id = re.sub(r"\s", "", id_match.group()) if id_match else None
    if key_id:
        nk = _norm(key_id)
        cands = [v for v in videos if nk in _norm(v.get("name", ""))]
        return max(cands, key=_date_rank) if cands else None

    # 2) 案件番号が無い予定のみ、名前の“固有部分”の一致で慎重に照合する。
    #    汎用語（初回商談/オンライン等）は除き、5文字以上の連続一致がある時だけ採用。
    #    日付の近さは候補の順位付け（タイブレーク）にのみ使い、単独では一致とみなさない。
    cleaned = summary or ""
    for g in ("初回商談", "商談", "オンライン", "打合せ", "打ち合わせ", "面談", "定例", "MTG", "mtg"):
        cleaned = cleaned.replace(g, "")
    n_spec = _norm(cleaned)
    if not n_spec:
        return None

    def _overlap(v: dict) -> int:
        n_name = _norm(v.get("name", ""))
        longest = 0
        for i in range(len(n_spec)):
            for j in range(i + 5, len(n_spec) + 1):
                if n_spec[i:j] in n_name and (j - i) > longest:
                    longest = j - i
        return longest

    best = max(videos, key=lambda v: (_overlap(v), _date_rank(v)))
    return best if _overlap(best) >= 5 else None
