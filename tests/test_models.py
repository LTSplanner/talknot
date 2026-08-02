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


def test_johari_parsed_and_roundtrips():
    data = dict(SAMPLE)
    data["johari"] = {
        "open_pct": "40", "blind_pct": 30, "hidden_pct": 20, "unknown_pct": 10,
        "comment": "秘密領域にもっと時間を",
    }
    r = EvaluationResult.from_dict(data)
    assert r.johari is not None
    assert r.johari.open_pct == 40 and r.johari.value_pct == 50  # 盲点30+秘密20
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.johari.hidden_pct == 20 and again.johari.comment == "秘密領域にもっと時間を"


def test_johari_absent_is_none():
    assert EvaluationResult.from_dict({}).johari is None


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


def test_customer_profile_parsed_and_roundtrips():
    data = dict(SAMPLE)
    data["customer_profile"] = {
        "attributes": ["慎重", "価格重視", "家族相談型"],
        "summary": "即決はせず持ち帰って家族に相談するタイプ。",
        "next_approach": "根拠を先に示し、比較しやすい形で提案する。",
    }
    r = EvaluationResult.from_dict(data)
    assert r.customer_profile is not None
    assert r.customer_profile.attributes == ["慎重", "価格重視", "家族相談型"]
    assert r.customer_profile.summary.startswith("即決")
    again = EvaluationResult.from_dict(r.to_dict())
    assert again.customer_profile.attributes == ["慎重", "価格重視", "家族相談型"]
    assert again.customer_profile.next_approach.startswith("根拠")


def test_customer_profile_absent_is_none():
    """過去データ（customer_profile 無し）でも None で後方互換に読める。"""
    assert EvaluationResult.from_dict({}).customer_profile is None
    assert EvaluationResult.from_dict(SAMPLE).customer_profile is None
    # round-trip でも None のまま保たれる
    assert EvaluationResult.from_dict(
        EvaluationResult.from_dict(SAMPLE).to_dict()
    ).customer_profile is None


def test_customer_profile_normalizes_bad_attributes():
    """attributes が非list・str項目欠損でも落ちず正規化される。"""
    r = EvaluationResult.from_dict(
        {"customer_profile": {"attributes": "せっかち"}}  # 非list
    )
    assert r.customer_profile.attributes == []
    assert r.customer_profile.summary == ""
    assert r.customer_profile.next_approach == ""


# --- Before に「お客様の発言」が混入する話者取り違えの防止 -------------------
# 実際に本番で出てしまった 2 件をそのまま回帰テストにしている。

def test_before_falls_back_to_empty_when_it_echoes_customer_line():
    """before がお客様の発言そのものなら、営業トークとして表示しない。"""
    data = {"feedback": [{
        "timestamp": "17:38",
        "criterion_key": "emotion",
        "emotion_note": "お客様はエコカラットの消臭・調湿効果について"
                        "「なんか気持ち程度なのかなって勝手に思ってたんですけど」と半信半疑な様子。",
        "before": "なんか気持ち程度なのかなって勝手に思ってたんですけど。",
        "after": "そうですよね、実際に使ってみないと効果が分かりにくいかもしれません。",
    }]}
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before == ""
    assert "気持ち程度" in f.customer_line
    assert f.after.startswith("そうですよね")


def test_before_echo_detected_from_customer_line_field():
    data = {"feedback": [{
        "timestamp": "23:12",
        "criterion_key": "flexibility",
        "emotion_note": "お客様は玄関ミラーについて困惑している。",
        "customer_line": "いや、そうなんすね。ミラーも欲しかったんですけど、"
                         "なんかあんまりつけるところがないなと言いますか。",
        "before": "いや、そうなんすね。ミラーも欲しかったんですけど、"
                  "なんかあんまりつけるところがないなと言いますか。",
        "after": "ミラーの設置場所、確かに悩ましいですよね。",
    }]}
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before == ""
    assert f.customer_line.startswith("いや、そうなんすね")


def test_genuine_sales_talk_is_kept():
    """営業本人のトークは当然そのまま残る（過検出しない）。"""
    data = {"feedback": [{
        "timestamp": "05:00",
        "criterion_key": "emotion",
        "emotion_note": "お客様は「予算が心配で」と不安そう。",
        "customer_line": "予算が心配で",
        "before": "ご予算については後ほどまとめてご説明しますね。",
        "after": "ご予算のご不安、先に伺ってもよろしいですか？",
    }]}
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before == "ご予算については後ほどまとめてご説明しますね。"


def test_parroting_back_the_customer_is_not_flagged():
    """お客様の言葉を受け止めて返すオウム返しは、正当な営業トークなので残す。"""
    data = {"feedback": [{
        "timestamp": "06:00",
        "criterion_key": "emotion",
        "emotion_note": "お客様は「デザインが重いかなって」と迷っている。",
        "customer_line": "デザインが重いかなって",
        "before": "デザインが重いかな、と感じられるんですね。"
                  "どのあたりがそう思われますか？色味でしょうか、それとも面積でしょうか。",
        "after": "デザインが重く感じられるんですね。どんな雰囲気がお好みですか？",
    }]}
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before.startswith("デザインが重いかな、と感じられるんですね")
