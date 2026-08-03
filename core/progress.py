"""ステップアップの仕組み：前回の『1ポイント』を次の評価へ引き継ぐ純ロジック。

評価が毎回バラバラの指摘で終わると、プランナーは何を積み上げているのか分からない。
そこで「前回出した1点」を次の商談・ロープレの評価に渡し、

    前回の宿題 → 今回できたかの答え合わせ → 次の1点（未達なら継続／達成なら次の段階）

という流れにする。商談とロープレは同じ人の成長として1本の線でつなぐ（ロープレで
練習した1点が、次の商談でできているかを見る）。

外部I/Oは持たない（呼び出し側が storage.list_evaluations() の結果を渡す）。
"""
from __future__ import annotations


def _saved_at(record: dict) -> str:
    return str(record.get("saved_at") or "")


def latest_one_point(records: list[dict]) -> dict | None:
    """評価履歴から、直近に出した『次に直す1点』を取り出す。

    records は services.storage.list_evaluations() の返り値を想定
    （{status, saved_at, label, result} を持つ dict のリスト）。
    完了した評価のうち最も新しいものから探し、1ポイントを持つ最初の1件を返す。
    まだ1件も無ければ None（＝初回なので答え合わせをしない）。

    戻り値: {headline, action, label, saved_at}
    """
    for rec in sorted(records or [], key=_saved_at, reverse=True):
        if rec.get("status") != "done":
            continue
        result = rec.get("result")
        if not isinstance(result, dict):
            continue
        op = result.get("one_point")
        if not isinstance(op, dict):
            continue
        headline = (op.get("headline") or "").strip()
        if not headline:
            continue
        return {
            "headline": headline,
            "action": (op.get("action") or "").strip(),
            "label": str(rec.get("label") or "").strip(),
            "saved_at": _saved_at(rec)[:10],
        }
    return None
