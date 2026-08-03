"""ステップアップの仕組み（前回の1ポイントの引き継ぎ）のテスト。"""
from core import prompts
from core.models import EvaluationResult
from core.progress import latest_one_point


def _rec(saved_at: str, headline: str = "", status: str = "done", label: str = "商談A"):
    result = {"scores": []}
    if headline:
        result["one_point"] = {"headline": headline, "action": f"「{headline}」と言う"}
    return {"saved_at": saved_at, "status": status, "label": label, "result": result}


def test_picks_the_newest_one_point():
    records = [
        _rec("2026-08-01 10:00", "背景を2問聞く"),
        _rec("2026-08-03 09:00", "見積提出の日を決める"),
        _rec("2026-07-28 18:00", "沈黙を待つ"),
    ]
    got = latest_one_point(records)
    assert got["headline"] == "見積提出の日を決める"
    assert got["saved_at"] == "2026-08-03"


def test_skips_records_without_one_point():
    """1ポイントが無い過去データは飛ばして、その前の宿題を拾う。"""
    records = [_rec("2026-08-03 09:00"), _rec("2026-08-01 10:00", "背景を2問聞く")]
    assert latest_one_point(records)["headline"] == "背景を2問聞く"


def test_skips_failed_and_processing_records():
    records = [
        _rec("2026-08-03 09:00", "失敗した回", status="error"),
        _rec("2026-08-02 09:00", "解析中の回", status="processing"),
        _rec("2026-08-01 10:00", "背景を2問聞く"),
    ]
    assert latest_one_point(records)["headline"] == "背景を2問聞く"


def test_first_time_has_no_homework():
    assert latest_one_point([]) is None
    assert latest_one_point([_rec("2026-08-03 09:00")]) is None


def test_prompt_carries_the_previous_homework():
    p = prompts.build_evaluation_prompt(previous_one_point={
        "headline": "商品説明の前に暮らしを2問聞く",
        "action": "「普段のお掃除で大変なところは？」",
        "label": "◎初回商談 矢野様", "saved_at": "2026-08-02",
    })
    assert "前回の宿題" in p
    assert "商品説明の前に暮らしを2問聞く" in p
    assert "follow_up" in p
    assert "まだできていなければ、同じ課題を継続" in p


def test_prompt_without_homework_omits_the_section():
    """初回は答え合わせの節を出さない（存在しない宿題を作らせない）。"""
    p = prompts.build_evaluation_prompt()
    assert "# 前回の宿題" not in p


def test_follow_up_parsed_and_roundtrips():
    r = EvaluationResult.from_dict({
        "scores": [],
        "follow_up": {
            "previous_headline": "商品説明の前に暮らしを2問聞く",
            "status": "partial",
            "timestamp": "03:20",
            "comment": "1問は聞けたが、そのまま説明へ進んだ。",
        },
    })
    assert r.follow_up.previous_headline == "商品説明の前に暮らしを2問聞く"
    assert r.follow_up.icon == "🔄"
    assert r.follow_up.label == "一部できていました"
    assert r.follow_up.achieved is False
    assert r.to_dict()["follow_up"]["status"] == "partial"


def test_follow_up_done_marks_achieved():
    r = EvaluationResult.from_dict({
        "scores": [],
        "follow_up": {"previous_headline": "沈黙を待つ", "status": "done"},
    })
    assert r.follow_up.achieved is True
    assert r.follow_up.icon == "✅"


def test_follow_up_absent_is_none():
    """初回評価・過去データでは None（画面に答え合わせを出さない）。"""
    assert EvaluationResult.from_dict({"scores": []}).follow_up is None
    assert EvaluationResult.from_dict({"follow_up": {}, "scores": []}).follow_up is None


def test_follow_up_unknown_status_is_neutral():
    """モデルが想定外の値を返しても壊れない。"""
    r = EvaluationResult.from_dict({
        "scores": [],
        "follow_up": {"previous_headline": "沈黙を待つ", "status": "たぶん"},
    })
    assert r.follow_up.achieved is False
    assert r.follow_up.label == "確認中"


def test_next_action_is_only_in_one_point():
    """改善の指示は1点に集約する（5項目の講評に次の一言を書かせない）。

    「1点に絞る」設計と「各項目にも次の一言」は矛盾するため、項目コメントの
    役割は点数の根拠に限定している。
    """
    p = prompts.build_evaluation_prompt()
    schema = p.split("# 出力フォーマット", 1)[1]
    assert "改善の指示は one_point に1つだけ書く" in schema
    assert "点数の根拠" in schema
