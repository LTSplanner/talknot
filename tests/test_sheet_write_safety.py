"""評価履歴の書き込み安全性のテスト。

実際に起きた事故：巨大な評価（指摘85件）でシートへの書き込みが 400 で失敗し、
「全消し→書き込み」の順だったためロープレ17件が巻き添えで消えた。
同じ失われ方を二度としないよう、ここで条件を固定する。
"""
import inspect
import json

from services.sheets_knowledge import _CELL_LIMIT, _fit_cell, save_evaluations


def _big_result(scenes: int = 150, needs: int = 80) -> str:
    return json.dumps({
        "one_point": {"headline": "商品説明の前に暮らしを2問聞く",
                      "action": "「一番大変なところはどこですか？」"},
        "summary": "全体としては丁寧に対応できていました。",
        "scores": [{"key": "emotion_catch", "sales_score": 4, "sales_comment": "良い"}],
        "feedback": [{"timestamp": f"{i}:00", "after": "あ" * 300} for i in range(scenes)],
        "hidden_needs": [{"inferred_need": "い" * 300} for _ in range(needs)],
    }, ensure_ascii=False)


def test_small_results_are_untouched():
    small = json.dumps({"summary": "短い評価"}, ensure_ascii=False)
    assert _fit_cell(small) == small
    assert _fit_cell("") == ""


def test_oversized_result_is_trimmed_to_fit():
    """1セルの上限を超えたら、収まるまで削る（書き込み自体を失敗させない）。"""
    raw = _big_result()
    assert len(raw) > _CELL_LIMIT
    out = _fit_cell(raw)
    assert len(out) <= _CELL_LIMIT
    json.loads(out)          # 壊れた JSON にしない


def test_the_important_parts_survive_trimming():
    """削るのは末尾の指摘だけ。1ポイント・スコア・振り返りは必ず残す。"""
    got = json.loads(_fit_cell(_big_result()))
    assert got["one_point"]["headline"] == "商品説明の前に暮らしを2問聞く"
    assert got["summary"].startswith("全体としては")
    assert len(got["scores"]) == 1
    assert got["_dropped"] > 0          # 何件削ったかを残す


def test_hidden_needs_are_dropped_before_scenes():
    """先に隠れたニーズを削る（場面の Before→After のほうが実務で使える）。"""
    got = json.loads(_fit_cell(_big_result(scenes=150, needs=80)))
    assert len(got["hidden_needs"]) < 80
    assert len(got["feedback"]) > 100    # 場面はできるだけ残る


def test_broken_json_is_cut_but_not_crashing():
    assert len(_fit_cell("あ" * (_CELL_LIMIT + 100))) <= _CELL_LIMIT


def test_write_happens_before_clearing_old_rows():
    """「全消し→書き込み」に戻さない。

    その順だと書き込み失敗でシートが空のまま残り、他人の記録まで失われる。
    """
    src = inspect.getsource(save_evaluations)
    update_at = src.index(".update(")
    clear_at = src.index(".clear(")
    assert update_at < clear_at, "update より先に clear してはいけない"
