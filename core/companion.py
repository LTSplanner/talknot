"""ロープレを続けると育つ相棒キャラクター（純ロジック・外部I/Oなし）。

称号バッジが「集める楽しみ」なら、こちらは「毎日会いに行く理由」を作る仕組み。

■ 設計の方針
- 育つのは **選んでいる1体だけ**。乗り換えた日から経験値の行き先が変わり、
  前の相棒はその時点の姿のまま図鑑に残る（＝自慢の1体を作れる）。
- 状態は**ほぼ保存しない**。保存するのは「いつ・どの子に乗り換えたか」だけで、
  経験値はロープレ履歴から毎回計算する（称号と同じ考え方）。あとから育ち方を
  調整しても、過去の実績にさかのぼって正しく反映される。
- **叱らない**。間が空いても退化も死にもしない。眠って待つだけで、1本やれば起きる。

保存する状態（services.storage.get_companion_state）の形：
    {"selected": "tori", "history": [{"date": "2026-08-01", "id": "tori"}, ...]}
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from core.companion_defs import (
    BY_ID,
    DEFAULT_ID,
    EXP_PER_GOOD,
    EXP_PER_SESSION,
    EXP_PER_STREAK_DAY,
    SPECIES,
    STAGE_COUNT,
    STAGE_THRESHOLDS,
    Species,
)

# 最後のロープレからの日数で決まる機嫌。(この日数以上, 呼び名, 絵文字)
_MOODS: list[tuple[int, str, str]] = [
    (7, "ねむっている", "😴"),
    (4, "さみしそう", "🥺"),
    (2, "ふつう", "🙂"),
    (1, "元気", "😊"),
    (0, "ごきげん", "🤗"),
]


@dataclass(frozen=True)
class Companion:
    """相棒1体の今の状態。"""
    species_id: str
    species_name: str    # 種族名（とり／ねこ…）
    name: str            # いまの姿の名前（ひよこ／こねこ…）
    icon: str            # 絵文字
    description: str     # いまの姿の説明
    stage: int           # 何段階目か（1から）
    stage_count: int     # 全段階数
    exp: int             # その相棒が貯めた経験値
    exp_in_stage: int    # いまの段階で貯まった経験値
    exp_for_next: int    # 次の段階までに必要な経験値（最終段階なら0）
    sessions: int        # その相棒と一緒にやったロープレ回数
    unlocked: bool = True    # 図鑑で解放済みか
    unlock_label: str = ""   # 未解放のときの条件文
    selected: bool = False   # いま育てている1体か
    # 以下は「いま育てている1体」だけが持つ（他は既定値のまま）
    mood: str = ""
    mood_icon: str = ""
    days_since: int = -1     # 最後のロープレからの日数（未実施なら -1）
    streak: int = 0          # いま続いている連続日数
    message: str = ""        # 相棒からの一言

    @property
    def progress(self) -> float:
        """次の段階までの進み具合 0.0〜1.0（最終段階は 1.0）。"""
        if self.exp_for_next <= 0:
            return 1.0
        return min(1.0, self.exp_in_stage / (self.exp_in_stage + self.exp_for_next))

    @property
    def is_max(self) -> bool:
        return self.stage >= self.stage_count


def _stage_index(exp: int) -> int:
    """経験値から段階の添字（0から）を求める。"""
    index = 0
    for i, need in enumerate(STAGE_THRESHOLDS):
        if exp >= need:
            index = i
    return index


def _mood_for(days_since: int) -> tuple[str, str]:
    """最後のロープレからの日数で機嫌を決める。"""
    if days_since < 0:
        return "まっている", "🥚"
    for threshold, name, icon in _MOODS:
        if days_since >= threshold:
            return name, icon
    return "ごきげん", "🤗"


def _message(days_since: int, streak: int, sessions: int) -> str:
    """相棒からの一言。責めず、次の1本へつなげる言い方にする。"""
    if sessions == 0:
        return "はじめまして。1本やると、ここから生まれます。"
    if days_since <= 0:
        if streak >= 2:
            return f"今日もありがとう。{streak}日つづけて会えていますね。"
        return "今日も来てくれてうれしいです。"
    if days_since == 1:
        return "きのうはおつかれさまでした。今日も1本、いきましょう。"
    if days_since <= 3:
        return f"{days_since}日ぶりですね。待っていました。"
    if days_since <= 6:
        return "少し間が空きましたね。短くていいので、また声を聞かせてください。"
    return "ねむって待っています。1本やると、すぐ起きます。"


# --- 保存状態の読み書き ------------------------------------------------------ #

def normalize_state(state: dict | None) -> dict:
    """保存状態を安全な形に整える（壊れていても既定値で動かす）。"""
    state = state if isinstance(state, dict) else {}
    history = []
    for row in state.get("history") or []:
        if not isinstance(row, dict):
            continue
        date, sid = str(row.get("date", ""))[:10], str(row.get("id", ""))
        if sid in BY_ID and _as_date(date):
            history.append({"date": date, "id": sid})
    history.sort(key=lambda r: r["date"])
    selected = str(state.get("selected", "")) or (
        history[-1]["id"] if history else DEFAULT_ID)
    if selected not in BY_ID:
        selected = DEFAULT_ID
    return {"selected": selected, "history": history}


def switch_to(state: dict | None, species_id: str, today: str) -> dict:
    """相棒を乗り換える。今日ぶんから新しい子に経験値が入る。

    同じ日に何度も乗り換えても履歴は1行にまとめる（迷って戻しても汚れない）。
    """
    data = normalize_state(state)
    if species_id not in BY_ID:
        return data
    history = [r for r in data["history"] if r["date"] != today]
    history.append({"date": today, "id": species_id})
    history.sort(key=lambda r: r["date"])
    return {"selected": species_id, "history": history}


def _as_date(text: str):
    try:
        return _dt.date.fromisoformat(str(text)[:10])
    except (ValueError, TypeError):
        return None


def owner_on(history: list[dict], date: str) -> str:
    """その日のロープレが誰の経験値になるか（乗り換え履歴から決める）。"""
    owner = DEFAULT_ID
    for row in history:
        if row["date"] <= date:
            owner = row["id"]
        else:
            break
    return owner


# --- 経験値の集計 ------------------------------------------------------------ #

def _roleplay_days(records: list[dict]) -> list[tuple[str, bool]]:
    """ロープレ履歴を (日付, 良い回か) の古い順リストにする。"""
    from core import badges

    rows = [
        r for r in (records or [])
        if r.get("status") == "done" and badges.is_roleplay(r)
        and badges.result_of(r) is not None
    ]
    rows.sort(key=lambda r: str(r.get("saved_at", "")))
    out = []
    for r in rows:
        day = str(r.get("saved_at", ""))[:10]
        if not _as_date(day):
            continue
        total = badges._total(badges.result_of(r) or {})
        out.append((day, total >= badges.HIGH_SCORE_TOTAL))
    return out


def _best_streak(days: list[str]) -> int:
    """その相棒と続けた最高連続日数（土日をまたいでもつながる）。"""
    from core import badges

    return badges._max_consecutive_days(days)


def exp_table(records: list[dict], state: dict) -> dict[str, dict]:
    """相棒ごとの {経験値, 回数} を返す。選ばれていた期間の実績だけが入る。"""
    table: dict[str, dict] = {s.id: {"exp": 0, "sessions": 0, "days": []} for s in SPECIES}
    for day, good in _roleplay_days(records):
        owner = owner_on(state["history"], day)
        row = table.setdefault(owner, {"exp": 0, "sessions": 0, "days": []})
        row["exp"] += EXP_PER_SESSION + (EXP_PER_GOOD if good else 0)
        row["sessions"] += 1
        row["days"].append(day)
    for row in table.values():
        row["exp"] += _best_streak(row["days"]) * EXP_PER_STREAK_DAY
    return table


def _build(species: Species, exp: int, sessions: int, **extra) -> Companion:
    index = _stage_index(exp)
    name, icon, description = species.stages[index]
    need = STAGE_THRESHOLDS[index]
    next_need = STAGE_THRESHOLDS[index + 1] if index + 1 < STAGE_COUNT else 0
    return Companion(
        species_id=species.id, species_name=species.name,
        name=name, icon=icon, description=description,
        stage=index + 1, stage_count=STAGE_COUNT,
        exp=exp, exp_in_stage=exp - need,
        exp_for_next=max(0, next_need - exp) if next_need else 0,
        sessions=sessions, **extra,
    )


def _unlocked_ids(records: list[dict], table: dict[str, dict]) -> set[str]:
    """図鑑で解放済みの種族。条件は通算実績（乗り換えとは無関係）で判定する。"""
    from core import badges

    metrics = badges.compute_metrics(records, "roleplay")
    max_stage = max((_stage_index(row["exp"]) + 1 for row in table.values()), default=1)
    out = set()
    for s in SPECIES:
        if s.unlock_metric == "max_stage":
            got = max_stage
        else:
            got = float(metrics.get(s.unlock_metric, 0))
        if got >= s.unlock_value:
            out.add(s.id)
    out.add(DEFAULT_ID)   # 最初の1体は必ず一緒にいる
    return out


def compute(records: list[dict], today: str, state: dict | None = None) -> Companion:
    """いま育てている相棒の状態を返す（画面の一番上に出す1体）。"""
    data = normalize_state(state)
    table = exp_table(records, data)
    species = BY_ID.get(data["selected"], BY_ID[DEFAULT_ID])
    row = table.get(species.id, {"exp": 0, "sessions": 0})

    from core import badges

    streak = badges.current_day_streak(records, "roleplay", today)
    days_since = _days_since_last(records, today)
    mood, mood_icon = _mood_for(days_since)
    return _build(
        species, int(row["exp"]), int(row["sessions"]),
        selected=True, unlocked=True, unlock_label=species.unlock_label,
        mood=mood, mood_icon=mood_icon, days_since=days_since, streak=streak,
        message=_message(days_since, streak, int(row["sessions"])),
    )


def collection(records: list[dict], today: str, state: dict | None = None) -> list[Companion]:
    """図鑑。解放済みも未解放も、定義順に全部返す（未解放は条件文つき）。"""
    data = normalize_state(state)
    table = exp_table(records, data)
    unlocked = _unlocked_ids(records, table)
    selected = data["selected"]
    out = []
    for s in SPECIES:
        row = table.get(s.id, {"exp": 0, "sessions": 0})
        out.append(_build(
            s, int(row["exp"]), int(row["sessions"]),
            unlocked=s.id in unlocked, unlock_label=s.unlock_label,
            selected=s.id == selected,
        ))
    return out


def _days_since_last(records: list[dict], today: str) -> int:
    """最後にロープレをした日から何日経ったか。一度も無ければ -1。"""
    days = [d for d, _ in _roleplay_days(records)]
    if not days:
        return -1
    last, now = _as_date(max(days)), _as_date(today)
    if not last or not now:
        return -1
    return max(0, (now - last).days)


def summary_line(c: Companion) -> str:
    """リマインドなどに1行で添える成長報告。"""
    tail = "（最終段階）" if c.is_max else f"（次の姿まであと {c.exp_for_next}）"
    return f"{c.icon} {c.name}｜Lv.{c.stage} / {c.stage_count}{tail}"
