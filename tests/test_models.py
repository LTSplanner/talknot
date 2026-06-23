"""EvaluationResult の JSON ラウンドトリップと補助メソッドのテスト。"""
from core.models import EvaluationResult

SAMPLE = {
    "scores": [
        {
            "key": "emotion_catch",
            "reference_score": 3,
            "reference_comment": "模範に近い拾い方",
            "sales_score": 4,
            "sales_comment": "感情をよく拾えていた",
        },
        {
            "key": "excitement",
            "reference_score": 4,
            "reference_comment": "あと一歩で模範級",
            "sales_score": 5,
            "sales_comment": "ワクワク感が高まった",
        },
    ],
    "feedback": [
        {
            "timestamp": "03:12",
            "criterion_key": "emotion_catch",
            "emotion_note": "不安そうな間があった",
            "before": "大丈夫ですよ",
            "after": "ご不安ですよね、と一度受け止める",
        }
    ],
    "summary": "全体的に好印象でした",
}


def test_from_dict_parses_all_fields():
    r = EvaluationResult.from_dict(SAMPLE)
    assert len(r.scores) == 2
    assert len(r.feedback) == 1
    assert r.feedback[0].timestamp == "03:12"
    assert r.feedback[0].after.startswith("ご不安")
    assert r.summary == "全体的に好印象でした"


def test_two_axis_totals_and_score_for():
    r = EvaluationResult.from_dict(SAMPLE)
    assert r.sales_total == 9          # 4 + 5
    assert r.reference_total == 7      # 3 + 4
    assert r.total == r.sales_total    # 後方互換は営業視点の合計
    assert r.score_for("excitement").sales_score == 5
    assert r.score_for("excitement").reference_score == 4
    assert r.score_for("unknown") is None


def test_roundtrip_to_dict():
    r = EvaluationResult.from_dict(SAMPLE)
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.sales_total == r.sales_total
    assert again.reference_total == r.reference_total
    assert again.feedback[0].before == r.feedback[0].before


def test_legacy_single_score_is_applied_to_both_axes():
    """旧形式（score/comment のみ）も両軸に流用して読めること。"""
    r = EvaluationResult.from_dict(
        {"scores": [{"key": "excitement", "score": 5, "comment": "良い"}]}
    )
    s = r.score_for("excitement")
    assert s.reference_score == 5 and s.sales_score == 5
    assert s.reference_comment == "良い" and s.sales_comment == "良い"


def test_from_dict_tolerates_missing_fields():
    r = EvaluationResult.from_dict({})
    assert r.scores == [] and r.feedback == [] and r.summary == ""
    assert r.total == 0 and r.reference_total == 0
    assert r.knowledge == []


def test_hidden_needs_parsed_and_roundtrips():
    data = dict(SAMPLE)
    data["hidden_needs"] = [
        {
            "timestamp": "05:40",
            "signal": "予算の話で急に声が小さくなった",
            "inferred_need": "本当は予算オーバーが不安",
            "surfaced": "false",  # 文字列でも bool に変換される
            "note": "金額の沈黙を拾って触れるべきだった",
        },
        {"inferred_need": ""},  # 中身が無い項目は捨てる
    ]
    r = EvaluationResult.from_dict(data)
    assert len(r.hidden_needs) == 1
    h = r.hidden_needs[0]
    assert h.surfaced is False and h.inferred_need == "本当は予算オーバーが不安"
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.hidden_needs[0].signal == "予算の話で急に声が小さくなった"
    assert again.hidden_needs[0].surfaced is False


def test_hidden_needs_default_empty():
    assert EvaluationResult.from_dict({}).hidden_needs == []


def test_knowledge_parsed_and_roundtrips():
    data = dict(SAMPLE)
    data["knowledge"] = [
        {"category": "product", "point": "ZEH仕様は補助金対象"},
        {"category": "technique", "point": ""},  # 空は捨てる
    ]
    r = EvaluationResult.from_dict(data)
    assert len(r.knowledge) == 1
    assert r.knowledge[0].category == "product"
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.knowledge[0].point == "ZEH仕様は補助金対象"
