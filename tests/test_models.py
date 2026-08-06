"""EvaluationResult の JSON ラウンドトリップと補助メソッドのテスト。"""
from config import settings
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


def test_one_point_parsed_and_roundtrips():
    """『次に直す1点』が復元でき、to_dict でも往復する。"""
    data = {
        "one_point": {
            "headline": "商品説明の前に暮らしを2問聞く",
            "timestamp": "05:12",
            "reason": "5分過ぎからコーティングの説明が続き、お客様の相槌が短くなった。",
            "action": "「差し支えなければ、普段のお掃除で一番大変なところを教えてください」",
            "keep": "冒頭の自己紹介で施工実績を具体的に伝えられていた。",
        },
        "scores": [],
    }
    r = EvaluationResult.from_dict(data)
    assert r.one_point is not None
    assert r.one_point.headline == "商品説明の前に暮らしを2問聞く"
    assert r.one_point.timestamp == "05:12"
    assert "お掃除" in r.one_point.action
    assert r.to_dict()["one_point"]["keep"].startswith("冒頭の自己紹介")


def test_one_point_absent_is_none():
    """過去データ（1ポイントが無い評価）でも壊れない。"""
    assert EvaluationResult.from_dict({"scores": []}).one_point is None
    assert EvaluationResult.from_dict({"one_point": {}, "scores": []}).one_point is None


def test_industry_term_mishearings_are_fixed():
    """音声認識が業界用語を同音の一般語にした場合、コード側で直す。

    新築インテリアオプションの用語（入隅・角）は一般語に誤変換されやすく、
    プロンプトだけに任せると残ってしまうため。
    """
    data = {
        "scores": [],
        "feedback": [{
            "timestamp": "00:43",
            "criterion_key": "emotion_catch",
            "emotion_note": "受け身な様子",
            "customer_line": "ここの入り墨はどうなりますか",
            "before": "お部屋の入り墨ですね。門になる部分から60cmで",
            "after": "入隅の納まりをご説明しますね",
        }],
    }
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before == "お部屋の入隅ですね。角になる部分から60cmで"
    assert f.customer_line == "ここの入隅はどうなりますか"


def test_term_fix_applies_to_summary_and_one_point():
    """要約や1ポイントアドバイスの文中でも同じ補正がかかる。"""
    r = EvaluationResult.from_dict({
        "scores": [],
        "summary": "エコガラスの提案が良かった",
        "one_point": {"headline": "入り墨の説明を先に", "action": "「入り墨から測ります」"},
    })
    assert r.summary == "エコカラットの提案が良かった"
    assert r.one_point.headline == "入隅の説明を先に"
    assert "入隅" in r.one_point.action


def _needs(n):
    return {"scores": [],
            "hidden_needs": [
                {"timestamp": f"0{i}:00", "signal": "間", "inferred_need": f"不安{i}",
                 "surfaced": False, "note": ""}
                for i in range(1, n + 1)]}


def test_hidden_needs_are_not_capped_by_default():
    """既定では絞らない。上限を設けると商談の前半だけで打ち切られるため。"""
    assert settings.MAX_HIDDEN_NEEDS == 0
    assert len(EvaluationResult.from_dict(_needs(8)).hidden_needs) == 8


def test_hidden_needs_capped_when_a_limit_is_set(monkeypatch):
    """異常に多いときのために、上限を設定すれば効く（重要な順に採る）。"""
    monkeypatch.setattr(settings, "MAX_HIDDEN_NEEDS", 3)
    got = EvaluationResult.from_dict(_needs(5)).hidden_needs
    assert [h.inferred_need for h in got] == ["不安1", "不安2", "不安3"]


def test_feedback_is_sorted_into_time_order():
    """モデルが時系列を前後させても、必ず昇順で読めるようにする。

    実際に 02:44:07 の次に 01:50:50 が返ってきた。商談の流れを追うものなので
    順番はコード側で保証する。
    """
    data = {"scores": [], "feedback": [
        {"timestamp": "01:15:32", "after": "a"},
        {"timestamp": "02:44:07", "after": "b"},
        {"timestamp": "01:50:50", "after": "c"},
        {"timestamp": "06:23", "after": "d"},
    ]}
    got = [f.timestamp for f in EvaluationResult.from_dict(data).feedback]
    assert got == ["06:23", "01:15:32", "01:50:50", "02:44:07"]


def test_roleplay_turn_numbers_sort_numerically():
    """ロープレの "T2" は文字列順（T10 < T2）にならないよう数値で並べる。"""
    data = {"scores": [], "feedback": [
        {"timestamp": "T10", "after": "a"},
        {"timestamp": "T2", "after": "b"},
    ]}
    got = [f.timestamp for f in EvaluationResult.from_dict(data).feedback]
    assert got == ["T2", "T10"]


def test_unreadable_timestamps_keep_their_order_at_the_end():
    data = {"scores": [], "feedback": [
        {"timestamp": "", "after": "x"},
        {"timestamp": "05:00", "after": "y"},
        {"timestamp": "なし", "after": "z"},
    ]}
    got = [f.after for f in EvaluationResult.from_dict(data).feedback]
    assert got == ["y", "x", "z"]


def test_hidden_needs_are_also_time_ordered():
    data = {"scores": [], "hidden_needs": [
        {"timestamp": "20:00", "inferred_need": "b"},
        {"timestamp": "05:00", "inferred_need": "a"},
    ]}
    got = [h.inferred_need for h in EvaluationResult.from_dict(data).hidden_needs]
    assert got == ["a", "b"]


def test_unknown_score_keys_are_dropped():
    """定義外の評価項目は合計に混ぜない。

    AI が勝手なキー（natural_needs_発掘 など）を返し、6項目目として加算されて
    合計 26/25 という上限超えが実際に起きた。画面にも出せないキーなので捨てる。
    """
    data = {"scores": [
        {"key": "emotion_catch", "sales_score": 5},
        {"key": "background_depth", "sales_score": 5},
        {"key": "additional_consideration", "sales_score": 5},
        {"key": "adaptability", "sales_score": 5},
        {"key": "excitement", "sales_score": 5},
        {"key": "natural_needs_発掘", "sales_score": 4},
    ]}
    r = EvaluationResult.from_dict(data)
    assert len(r.scores) == len(settings.EVALUATION_CRITERIA)
    assert r.overall_total == 25          # 満点を超えない
    assert r.score_for("natural_needs_発掘") is None


def test_runaway_repetition_is_collapsed():
    """AI がループして同じ語を繰り返した出力を、読める長さに畳む。

    実際に before へ「もちろん」が数百回入り、画面が埋まる事故が起きた。
    """
    data = {"scores": [], "feedback": [{
        "timestamp": "51:55",
        "before": "もちろん" * 300,
        "after": "かしこまりました。",
        "customer_line": "一応外しても大丈夫ですか？",
    }]}
    f = EvaluationResult.from_dict(data).feedback[0]
    assert f.before == "もちろんもちろん…"
    assert f.after == "かしこまりました。"      # 正常な文は変わらない


def test_short_natural_repeats_are_kept():
    """「はいはい」のような自然な繰り返しは畳まない。"""
    data = {"scores": [], "feedback": [
        {"before": "はいはい、承知しました。ではご案内しますね。", "after": "x"}]}
    got = EvaluationResult.from_dict(data).feedback[0].before
    assert got == "はいはい、承知しました。ではご案内しますね。"


def test_absurdly_long_utterance_is_cut():
    """繰り返しでなくても、発言として長すぎるものは打ち切る。"""
    data = {"scores": [], "feedback": [
        {"before": "".join(chr(0x3042 + i % 80) for i in range(2000)), "after": "x"}]}
    got = EvaluationResult.from_dict(data).feedback[0].before
    assert len(got) <= 801 and got.endswith("…")
