"""EvaluationResult の JSON ラウンドトリップと補助メソッドのテスト。"""
from core.models import EvaluationResult

SAMPLE = {
    "scores": [
        {"key": "emotion_catch", "score": 4, "comment": "感情をよく拾えていた"},
        {"key": "excitement", "score": 5, "comment": "ワクワク感が高まった"},
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


def test_total_and_score_for():
    r = EvaluationResult.from_dict(SAMPLE)
    assert r.total == 9
    assert r.score_for("excitement").score == 5
    assert r.score_for("unknown") is None


def test_roundtrip_to_dict():
    r = EvaluationResult.from_dict(SAMPLE)
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.total == r.total
    assert again.feedback[0].before == r.feedback[0].before


def test_from_dict_tolerates_missing_fields():
    r = EvaluationResult.from_dict({})
    assert r.scores == [] and r.feedback == [] and r.summary == ""
    assert r.total == 0
