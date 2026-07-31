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

# --- 休み（送信スキップ）判定用のキーワード ---------------------------------- #
# イベントのタイトルに次の「OFF語」を含むと、その日は休みとみなす（送らない）。
# 実運用では終日でなく時間指定で入る（例「中谷OFF 09:00〜22:00」）ため、
# 終日/時間指定を問わずタイトルのキーワードだけで判定する。
# ※「中抜け」「私用中抜け」等の部分中抜けは稼働扱いなので OFF語に含めない。
OFF_KEYWORDS: tuple[str, ...] = (
    "off", "お休み", "休み", "有給", "有休", "休暇", "全休", "代休",
    "振替休日", "振休", "夏季休暇", "冬季休暇", "年末年始", "全社休業", "会社休",
    "リフレッシュ休暇", "特別休暇", "産休", "育休", "慶弔",
)
# ただし「半休語」を含むイベントは稼働扱い（送る）。OFF語を含んでいても休みにしない。
# 例: 「午前休」「午後休」「半休」「AM半休」「時間休」等。
HALFDAY_KEYWORDS: tuple[str, ...] = (
    "午前休", "午後休", "半休", "am半休", "pm半休", "時間休", "半日",
)
MORNING_OFF_KEYWORDS: tuple[str, ...] = (
    "午前休", "午前半休", "am半休",
)
AFTERNOON_OFF_KEYWORDS: tuple[str, ...] = (
    "午後休", "午後半休", "pm半休",
)


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


def did_roleplay_before(
    records: list[dict],
    email: str,
    today_jst_str: str,
    cutoff_hhmmss: str,
) -> bool:
    """JSTの当日、締切時刻より前にロープレを完了していれば True。

    ``saved_at`` は ``YYYY-MM-DD HH:MM:SS`` 形式を前提とする。
    締切ちょうど（例 12:00:00）は午前中の実施に含めない。
    """
    target = _norm_email(email)
    if not target:
        return False
    for rec in records:
        if _norm_email(rec.get("user_email")) != target:
            continue
        if not _is_roleplay(rec) or _record_date(rec) != today_jst_str:
            continue
        saved_at = (rec.get("saved_at") or "").strip()
        if len(saved_at) < 19:
            continue
        if saved_at[11:19] < cutoff_hhmmss:
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


def missed_before(
    records: list[dict],
    targets: list[str],
    today_jst_str: str,
    cutoff_hhmmss: str,
) -> list[str]:
    """締切時刻までに当日ロープレを完了していない対象者を返す。"""
    missed: list[str] = []
    seen: set[str] = set()
    for email in targets:
        key = _norm_email(email)
        if not key or key in seen:
            continue
        seen.add(key)
        if not did_roleplay_before(records, email, today_jst_str, cutoff_hhmmss):
            missed.append(email)
    return missed


def _contains_any(title: str, keywords) -> bool:
    """title（小文字化済み）に keywords のいずれかを含むか。"""
    return any(kw in title for kw in keywords)


def is_off_today(
    events: list[dict],
    *,
    off_keywords=OFF_KEYWORDS,
    halfday_keywords=HALFDAY_KEYWORDS,
) -> bool:
    """その日が「休み」かどうかをタイトル語で判定する（True ならリマインドを送らない）。

    events は ``{"title": str}`` の簡易形のリスト（``all_day`` は任意・判定に使わない）。
    実運用では OFF/休みが終日でなく時間指定で入る（例「中谷OFF 09:00〜22:00」）ため、
    終日/時間指定を問わずタイトルのキーワードだけで判定する。

    判定:
      - タイトルにOFF語を含み かつ 半休語を含まないイベントが1つでもあれば True（送らない）。
      - 半休語（午前休・午後休 等）を含むイベントは稼働扱いとし、休みにカウントしない
        （OFF語を含んでいても False 側）。半休は必ず送るため、この優先を崩さない。
      - 「事務DAY」「MTG」「私用中抜け」等はOFF語でないので休み扱いしない（送る）。
      - 「夏季休暇」等の会社休は終日/時間指定を問わず休み扱い（送らない）。
    大文字小文字は無視する。
    """
    for ev in events:
        title = (ev.get("title") or "").lower()
        # 半休語が入っていれば、そのイベントは休みにカウントしない（午前休/午後休を送る）。
        if _contains_any(title, halfday_keywords):
            continue
        if _contains_any(title, off_keywords):
            return True
    return False


def is_off_morning(events: list[dict]) -> bool:
    """午前中に勤務予定がなく、正午リマインドを送らない人なら True。

    全休に加えて午前休・AM半休は送信対象から外す。
    午後休・PM半休は午前勤務なので送信対象に残す。
    「半休」のように午前・午後が特定できない予定は、取りこぼし防止のため送信対象に残す。
    """
    for ev in events:
        title = (ev.get("title") or "").lower()
        if _contains_any(title, MORNING_OFF_KEYWORDS):
            return True
        if _contains_any(title, AFTERNOON_OFF_KEYWORDS):
            continue
        if _contains_any(title, HALFDAY_KEYWORDS):
            continue
        if _contains_any(title, OFF_KEYWORDS):
            return True
    return False
