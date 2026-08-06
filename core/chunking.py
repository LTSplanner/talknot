"""長い録画を区間に分けて解析し、結果を1つに束ねる純ロジック（外部I/Oなし）。

■ なぜ必要か
実測で、3時間の商談を丸ごと渡すと **冒頭5分ぶんの指摘しか返ってこなかった**
（隠れたニーズでも16分まで）。プロンプトで「終盤も見て」と指示しても変わらない。
モデルが長時間の動画の後半をほとんど処理しないのが原因で、文言では解決しない。

そこで録画を30〜40分ごとに切り、**区間ごとに解析**する。区間の中では確実に
最後まで読まれる。返ってきたタイムスタンプは区間の開始時刻ぶんずれているので、
ここで元の位置に戻してから1つの評価に束ねる。

区間の分割・結合はすべてこのモジュールの純関数で行い、動画の切り出しと
API 呼び出しは services.gemini_analyzer が受け持つ。
"""
from __future__ import annotations

import re

# 1区間の既定の長さ（秒）。長すぎると後半が読まれず、短すぎると回数と費用が増える。
DEFAULT_CHUNK_SEC = 30 * 60

# これ以下の録画は分割しない（1回で最後まで読める長さ）。
SPLIT_THRESHOLD_SEC = 45 * 60

# タイムスタンプらしき文字列（"MM:SS" / "HH:MM:SS"）。
_TS_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")


def plan_chunks(duration_sec: float, chunk_sec: int = DEFAULT_CHUNK_SEC) -> list[tuple[int, int]]:
    """録画を (開始秒, 終了秒) の区間に割る。

    短い録画は分割しない（1区間として返す）。最後の区間が極端に短くなるときは、
    ひとつ前の区間に足して、数十秒だけの解析が走らないようにする。
    """
    total = int(duration_sec or 0)
    if total <= 0:
        return []
    if total <= SPLIT_THRESHOLD_SEC:
        return [(0, total)]

    bounds = list(range(0, total, chunk_sec))
    chunks = [(s, min(s + chunk_sec, total)) for s in bounds]
    # 末尾が5分未満なら手前に併合する（短すぎる区間は文脈が足りない）。
    if len(chunks) > 1 and chunks[-1][1] - chunks[-1][0] < 5 * 60:
        last = chunks.pop()
        chunks[-1] = (chunks[-1][0], last[1])
    return chunks


def format_timestamp(seconds: int) -> str:
    """秒を "MM:SS"（1時間以上なら "HH:MM:SS"）にする。"""
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_timestamp(text: str) -> int | None:
    """"MM:SS" / "HH:MM:SS" を秒にする。読めなければ None。"""
    m = _TS_RE.match(text or "")
    if not m:
        return None
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def shift_timestamps(obj, offset_sec: int):
    """区間の解析結果に含まれる時刻を、録画全体での位置に直す。

    区間ごとに解析すると、返る時刻は「その区間の先頭からの経過」になる。
    そのままでは全区間で 00:xx が並んでしまうため、開始秒を足して元に戻す。
    タイムスタンプ以外の文字列は触らない。
    """
    if offset_sec <= 0:
        return obj
    if isinstance(obj, str):
        sec = parse_timestamp(obj)
        return format_timestamp(sec + offset_sec) if sec is not None else obj
    if isinstance(obj, dict):
        return {k: shift_timestamps(v, offset_sec) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shift_timestamps(v, offset_sec) for v in obj]
    return obj


def _avg(values: list[float]) -> int:
    return round(sum(values) / len(values)) if values else 0


def merge_results(parts: list[dict]) -> dict:
    """区間ごとの評価を1つに束ねる。

    - feedback / hidden_needs / knowledge … つなげる（時刻はすでに全体基準）
    - scores … 項目ごとに区間の平均（商談全体の実力として見るため）
    - johari … 区間の平均（会話配分は全体の比率が知りたい）
    - summary / one_point / customer_profile … ここでは決めない。
      全体を見て決め直すため、呼び出し側が別途まとめる（部分の寄せ集めにしない）。
    """
    parts = [p for p in parts if isinstance(p, dict)]
    if not parts:
        return {}
    if len(parts) == 1:
        return dict(parts[0])

    merged: dict = {"feedback": [], "hidden_needs": [], "knowledge": []}
    for p in parts:
        for key in merged:
            items = p.get(key)
            if isinstance(items, list):
                merged[key].extend(items)

    # スコアは項目ごとに平均する（区間で上手さが変わるため、全体の実力に均す）。
    by_key: dict[str, list[float]] = {}
    comments: dict[str, list[str]] = {}
    for p in parts:
        for s in p.get("scores") or []:
            key = s.get("key")
            if not key:
                continue
            try:
                by_key.setdefault(key, []).append(float(s.get("sales_score") or 0))
            except (TypeError, ValueError):
                pass
            if s.get("sales_comment"):
                comments.setdefault(key, []).append(str(s["sales_comment"]))
    merged["scores"] = [
        {
            "key": key,
            "sales_score": _avg(vals),
            "sales_comment": comments.get(key, [""])[0],
            "reference_score": _avg(vals),
            "reference_comment": "",
        }
        for key, vals in by_key.items()
    ]

    johari_keys = ("open_pct", "blind_pct", "hidden_pct", "unknown_pct")
    js = [p.get("johari") for p in parts if isinstance(p.get("johari"), dict)]
    if js:
        merged["johari"] = {
            k: _avg([float(j.get(k) or 0) for j in js]) for k in johari_keys
        }
        merged["johari"]["comment"] = next(
            (j.get("comment") for j in js if j.get("comment")), "")

    return merged
