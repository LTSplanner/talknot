"""称号バッジの判定エンジン（外部I/Oなし・テスト対象）。

プランナーが「自分は積み上げている」と実感できるように、評価履歴から
称号（バッジ）を判定してコレクションにする。ロープレ50個・商談50個の計100個。

■ 設計
バッジの取得状況は**保存しない**。評価履歴から毎回計算する。理由：
  - 履歴が唯一の真実になるので、取り違え・二重付与が起きない
  - あとからバッジを追加しても、**過去の実績にさかのぼって反映**される
  - 保存先（共有シート）を増やさずに済む

判定は「指標（metric）が閾値（threshold）以上か」だけに統一してある。
新しいバッジを足すときは core/badge_defs.py に1行足すだけでよく、
指標を増やしたいときだけ _METRICS に計算を足す。

指標はロープレ・商談それぞれで別々に集計する（ロープレの回数で商談の
バッジは埋まらない）。
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from config import settings

# ロープレの評価履歴は label がこの絵文字で始まる（app.py の判定と合わせる）。
_ROLEPLAY_PREFIX = "🎙️"

# 「高得点」とみなす合計点（5項目×5点＝25点満点で20点＝平均4.0）。
HIGH_SCORE_TOTAL = 20


@dataclass(frozen=True)
class Badge:
    """1つの称号。取得条件は「指標 metric が threshold 以上」で表す。"""
    id: str
    name: str           # 称号名
    description: str    # 取得条件（読んで分かる文）
    icon: str           # 絵文字
    category: str       # "roleplay"（ロープレ） / "meeting"（商談）
    family: str         # 同じ系統のまとまり（段階表示に使う）
    tier: int           # 系統の中の段階（1が最初）
    metric: str         # 判定に使う指標名
    threshold: float    # この値以上で取得


@dataclass(frozen=True)
class BadgeStatus:
    """1つの称号の取得状況。"""
    badge: Badge
    earned: bool
    current: float      # 今の指標の値
    threshold: float

    @property
    def progress(self) -> float:
        """達成率 0.0〜1.0（未取得バッジの進捗バー用）。"""
        if self.threshold <= 0:
            return 1.0
        return min(1.0, self.current / self.threshold)

    @property
    def remaining(self) -> float:
        """あと何回・何ポイントで取れるか。"""
        return max(0.0, self.threshold - self.current)


def is_roleplay(record: dict) -> bool:
    """評価履歴の1件がロープレか（商談評価でないか）。"""
    return str(record.get("label", "")).startswith(_ROLEPLAY_PREFIX)


def _usable(records: list[dict], category: str) -> list[dict]:
    """判定に使える履歴（完了かつ結果あり）を、古い順に並べて返す。"""
    want_roleplay = category == "roleplay"
    out = [
        r for r in (records or [])
        if r.get("status") == "done" and isinstance(r.get("result"), dict)
        and is_roleplay(r) == want_roleplay
    ]
    out.sort(key=lambda r: str(r.get("saved_at", "")))
    return out


def _total(result: dict) -> int:
    """1件の合計点（5項目の営業プロ視点の合計・25点満点）。"""
    total = 0
    for s in result.get("scores") or []:
        try:
            total += int(s.get("sales_score") or 0)
        except (TypeError, ValueError):
            pass
    return total


def _max_run(flags: list[bool]) -> int:
    """True が最大何回続いたか。"""
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def _max_consecutive_days(dates: list[str]) -> int:
    """実施日（YYYY-MM-DD）が最大何日連続したか。"""
    days = sorted({d for d in dates if d})
    best = run = 0
    prev: _dt.date | None = None
    for d in days:
        try:
            cur = _dt.date.fromisoformat(d)
        except ValueError:
            continue
        run = run + 1 if prev and (cur - prev).days == 1 else 1
        best = max(best, run)
        prev = cur
    return best


def compute_metrics(records: list[dict], category: str) -> dict[str, float]:
    """指標をまとめて計算する。バッジ判定はこの辞書だけを見る。

    records は services.storage.list_evaluations() の返り値を想定。
    category は "roleplay" / "meeting"。
    """
    rows = _usable(records, category)
    results = [r["result"] for r in rows]
    totals = [_total(res) for res in results]
    dates = [str(r.get("saved_at", ""))[:10] for r in rows]

    highs = [t >= HIGH_SCORE_TOTAL for t in totals]
    improves = [totals[i] > totals[i - 1] for i in range(1, len(totals))]
    homeworks = [
        (res.get("follow_up") or {}).get("status") == "done" for res in results
    ]

    metrics: dict[str, float] = {
        "count": len(rows),
        "high_total": sum(highs),
        "high_streak": _max_run(highs),
        "best_total": max(totals) if totals else 0,
        "improve_streak": _max_run(improves),
        "active_days": len({d for d in dates if d}),
        "day_streak": _max_consecutive_days(dates),
        "homework_done": sum(homeworks),
        "homework_streak": _max_run(homeworks),
    }

    # 秘密領域に踏み込めた回数・会話配分・抽出ナレッジ（商談で効いてくる指標）
    surfaced = 0
    value_zone_best = 0.0
    knowledge_total = 0
    for res in results:
        for h in res.get("hidden_needs") or []:
            if h.get("surfaced"):
                surfaced += 1
        j = res.get("johari") or {}
        try:
            value_zone_best = max(
                value_zone_best, float(j.get("blind_pct") or 0) + float(j.get("hidden_pct") or 0))
        except (TypeError, ValueError):
            pass
        knowledge_total += len(res.get("knowledge") or [])
    metrics["hidden_surfaced"] = surfaced
    metrics["value_zone_best"] = value_zone_best
    metrics["knowledge_total"] = knowledge_total

    # 評価項目ごとの「満点(5)を取った回数」
    for c in settings.EVALUATION_CRITERIA:
        n = 0
        for res in results:
            for s in res.get("scores") or []:
                if s.get("key") == c.key:
                    try:
                        n += int(s.get("sales_score") or 0) >= 5
                    except (TypeError, ValueError):
                        pass
        metrics[f"perfect_{c.key}"] = n

    return metrics


def evaluate(records: list[dict], badges: list[Badge] | None = None) -> list[BadgeStatus]:
    """全バッジの取得状況を返す（定義順）。"""
    from core.badge_defs import ALL_BADGES

    badges = ALL_BADGES if badges is None else badges
    metrics = {
        "roleplay": compute_metrics(records, "roleplay"),
        "meeting": compute_metrics(records, "meeting"),
    }
    out = []
    for b in badges:
        cur = float(metrics[b.category].get(b.metric, 0))
        out.append(BadgeStatus(
            badge=b, earned=cur >= b.threshold, current=cur, threshold=b.threshold))
    return out


def earned_count(statuses: list[BadgeStatus]) -> int:
    return sum(1 for s in statuses if s.earned)


def next_up(statuses: list[BadgeStatus], limit: int = 3) -> list[BadgeStatus]:
    """『次に取れそう』な未取得バッジを、達成率の高い順に返す。

    まだ1回も実施していない（達成率0）ものは、励ましにならないので出さない。
    """
    pending = [s for s in statuses if not s.earned and s.current > 0]
    pending.sort(key=lambda s: (-s.progress, s.remaining))
    return pending[:limit]
