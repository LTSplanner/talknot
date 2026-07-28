"""ロープレ習慣化リマインドの純ロジック（外部I/Oなし・テスト対象）。

評価レコード（services.sheets_knowledge.load_evaluations() の返り値）を入力に、
「その人がその日ロープレを実施したか」「当日未実施の対象者は誰か」を判定する。

前提となるレコード形状（このモジュールが参照する項目のみ）:
    - ``user_email``: 実施者のメール（例 "hkumada@life-time-support.com"）
    - ``saved_at``  : 保存日時の文字列（例 "2026-07-27 10:15:03"）。先頭10文字が JST 日付。
    - ``label``     : ロープレは "🎙️" で始まる（商談評価と区別するための目印）。

時刻はすべて JST（+9）前提。ネットワーク・カレンダー等の副作用は持たない。
"""
from __future__ import annotations

import datetime as _dt

# ロープレ評価のラベルに必ず付く目印（これで始まるものだけをロープレとみなす）。
ROLEPLAY_LABEL_PREFIX = "🎙️"

# JST（UTC+9）。日付の境界判定に使う。
JST = _dt.timezone(_dt.timedelta(hours=9))


def today_jst_str(now: _dt.datetime | None = None) -> str:
    """JST での「今日」を "YYYY-MM-DD" で返す。

    now を渡すとその時刻を基準にする（テスト用）。省略時は現在時刻。
    """
    base = now or _dt.datetime.now(JST)
    # tz 無し（naive）で渡された場合は JST とみなす。
    if base.tzinfo is None:
        base = base.replace(tzinfo=JST)
    return base.astimezone(JST).strftime("%Y-%m-%d")


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _record_date(record: dict) -> str:
    """レコードの saved_at から JST 日付部分（先頭10文字）を取り出す。"""
    return (record.get("saved_at") or "").strip()[:10]


def _is_roleplay(record: dict) -> bool:
    """ロープレ評価のレコードか（label が "🎙️" 始まりか）。"""
    return (record.get("label") or "").lstrip().startswith(ROLEPLAY_LABEL_PREFIX)


def did_roleplay_today(records: list[dict], email: str, today_jst_str: str) -> bool:
    """email の人が today（JST日付）にロープレ評価を持つなら True。

    - label が "🎙️" で始まるレコードのみをロープレとみなす（商談評価は除外）。
    - saved_at の先頭10文字（日付）が today_jst_str と一致するものを当日実施とみなす。
    - メールアドレスの大文字小文字・前後空白は無視して比較する。
    """
    target = _norm_email(email)
    if not target:
        return False
    for rec in records:
        if _norm_email(rec.get("user_email")) != target:
            continue
        if not _is_roleplay(rec):
            continue
        if _record_date(rec) == today_jst_str:
            return True
    return False


def missed_today(
    records: list[dict], targets: list[str], today_jst_str: str
) -> list[str]:
    """対象者(targets)のうち、当日ロープレ未実施のメール一覧を返す。

    - targets の並び順を保ちつつ、重複は除いて返す。
    - 判定は did_roleplay_today と同じ基準（"🎙️" ラベル＋当日日付）。
    """
    missed: list[str] = []
    seen: set[str] = set()
    for email in targets:
        key = _norm_email(email)
        if not key or key in seen:
            continue
        seen.add(key)
        if not did_roleplay_today(records, email, today_jst_str):
            missed.append(email)
    return missed
