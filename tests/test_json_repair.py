"""途中で切れた Gemini 応答（JSON）の救済処理のテスト。

出力上限に当たると応答は文字列の途中でぶつ切りになる。全部捨てるのではなく、
そこまでに読めた評価を活かせることを確かめる。
"""
import json

import pytest

from core.models import EvaluationResult
from services.gemini_analyzer import _loads_lenient, repair_truncated_json


def test_intact_json_is_returned_as_is():
    src = '{"summary": "よい商談", "scores": []}'
    assert json.loads(repair_truncated_json(src)) == json.loads(src)


def test_truncated_in_the_middle_of_a_string():
    """文字列の途中で切れても、直前までに完成した項目は残る。"""
    src = '{"summary": "よい商談", "feedback": [{"timestamp": "01:00", "after": "こう言え'
    got = json.loads(repair_truncated_json(src))
    assert got["summary"] == "よい商談"
    # 書きかけのフィードバック（timestamp だけ）は残さない
    assert got.get("feedback", []) == []


def test_truncated_after_a_complete_list_item():
    """完成した要素は残し、壊れた要素だけ落とす。"""
    src = (
        '{"scores": [{"key": "a", "sales_score": 4}, {"key": "b", "sales_sc'
    )
    got = json.loads(repair_truncated_json(src))
    assert got["scores"] == [{"key": "a", "sales_score": 4}]


def test_truncated_with_nested_objects():
    src = (
        '{"one_point": {"headline": "暮らしを2問聞く", "action": "「どんな時に」"}, '
        '"feedback": [{"timestamp": "02:10", "before": "えっと、こち'
    )
    got = json.loads(repair_truncated_json(src))
    assert got["one_point"]["headline"] == "暮らしを2問聞く"
    assert got.get("feedback", []) == []


def test_escaped_quote_inside_string_is_not_a_boundary():
    """文字列内のエスケープされた引用符を構造の区切りと誤認しない。"""
    src = '{"summary": "彼は\\"理想の家\\"と言った", "scores": [], "knowledge": [{"point'
    got = json.loads(repair_truncated_json(src))
    assert got["summary"] == '彼は"理想の家"と言った'


def test_repaired_result_builds_a_usable_evaluation():
    """救済した JSON がそのまま評価結果として使える。"""
    src = (
        '{"one_point": {"headline": "商品説明の前に暮らしを2問聞く", '
        '"timestamp": "05:12", "action": "「一番大変なところは？」", "reason": "", "keep": ""}, '
        '"scores": [{"key": "emotion_catch", "sales_score": 3, "sales_comment": "良い"}], '
        '"feedback": [{"timestamp": "01:00", "before": "途中で切れ'
    )
    r = EvaluationResult.from_dict(json.loads(repair_truncated_json(src)))
    assert r.one_point.headline == "商品説明の前に暮らしを2問聞く"
    assert r.score_for("emotion_catch").sales_score == 3
    assert r.feedback == []


def test_no_recoverable_position_raises():
    with pytest.raises(ValueError):
        repair_truncated_json('{"summary": "切れ')
    with pytest.raises(ValueError):
        repair_truncated_json("JSONではない文字列")


def test_loads_lenient_only_repairs_when_asked():
    """既定では救済しない（まず再生成リトライさせるため）。"""
    broken = '{"summary": "よい商談", "feedback": [{"timestamp": "01:0'
    with pytest.raises(json.JSONDecodeError):
        _loads_lenient(broken)
    assert _loads_lenient(broken, repair=True)["summary"] == "よい商談"


def test_loads_lenient_strips_code_fence():
    fenced = '```json\n{"summary": "よい商談"}\n```'
    assert _loads_lenient(fenced)["summary"] == "よい商談"


def test_transient_network_errors_are_retried():
    """通信断は待って投げ直す（長い応答の生成中に実際に3件failした）。"""
    from services.gemini_analyzer import _is_transient

    assert _is_transient(Exception("Server disconnected without sending a response."))
    assert _is_transient(Exception("Connection reset by peer"))
    assert _is_transient(Exception("503 Service Unavailable"))
    # 内容の誤りは投げ直さない（何度やっても同じ）
    assert not _is_transient(Exception("400 INVALID_ARGUMENT: bad request"))
    assert not _is_transient(Exception("API key not valid"))
