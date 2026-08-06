"""商談の確定情報（予定タイトルの解析とプロンプト反映）のテスト。"""
from core import prompts
from core.meeting_context import (
    build_meeting_context,
    fill_customer_placeholders,
    known_names,
    parse_meeting_title,
)


def test_parses_standard_title():
    """社内書式『…案件番号　お客様名様｜物件名』から3つとも取り出せる。"""
    got = parse_meeting_title(
        "初回商談 SR L260722484601　福島慶紀様｜朝霞市三原3丁目の新築マンション"
    )
    assert got["case_id"] == "L260722484601"
    assert got["customer_name"] == "福島慶紀様"
    assert got["property_name"] == "朝霞市三原3丁目の新築マンション"


def test_parses_title_with_marker_and_inner_space():
    """◎付き・名前の中に全角空白があるタイトルも扱える。"""
    got = parse_meeting_title(
        "◎初回商談 オンライン L260719483601　池田　由里絵様｜ルネ柏ディアパーク　1020号室"
    )
    assert got["case_id"] == "L260719483601"
    assert got["customer_name"] == "池田 由里絵様"
    assert got["property_name"] == "ルネ柏ディアパーク 1020号室"


def test_parses_title_without_property():
    """物件名の区切りが無ければ、お客様名だけ取れて物件は空。"""
    got = parse_meeting_title("初回仕様MT オンライン L260707478901　安宮綾水様")
    assert got["customer_name"] == "安宮綾水様"
    assert got["property_name"] == ""


def test_parses_title_without_case_id():
    """案件番号が無いタイトルでは、一般語を除いてお客様名を拾う。"""
    got = parse_meeting_title("初回商談 オンライン　佐藤様｜Brillia City")
    assert got["case_id"] == ""
    assert got["customer_name"] == "佐藤様"
    assert got["property_name"] == "Brillia City"


def test_empty_title_is_safe():
    got = parse_meeting_title("")
    assert got == {"case_id": "", "customer_name": "", "property_name": ""}


def test_build_context_adds_planner_and_date():
    ctx = build_meeting_context(
        "初回商談 SR L260722484601　福島慶紀様｜朝霞市三原", "安栗実沙", "2026-08-02"
    )
    assert ctx["planner_name"] == "安栗実沙"
    assert ctx["meeting_date"] == "2026-08-02"
    assert known_names(ctx) == ["安栗実沙", "福島慶紀様", "朝霞市三原"]


def test_context_with_only_planner_name():
    """ファイル名など書式が保証されない経路では、氏名だけ渡せる。"""
    ctx = build_meeting_context("", "安栗実沙")
    assert ctx["planner_name"] == "安栗実沙"
    assert ctx["customer_name"] == ""
    assert known_names(ctx) == ["安栗実沙"]


def test_prompt_includes_confirmed_names():
    """確定情報がプロンプトに入り、当て字を禁じる指示も出る。"""
    ctx = build_meeting_context(
        "初回商談 SR L260722484601　福島慶紀様｜朝霞市三原", "安栗実沙", "2026-08-02"
    )
    p = prompts.build_evaluation_prompt(meeting_context=ctx)
    assert "安栗実沙" in p
    assert "福島慶紀様" in p
    assert "L260722484601" in p
    assert "確定情報" in p


def test_prompt_without_context_is_unchanged_shape():
    """確定情報が無くても従来どおりのプロンプトが作れる（確定情報の節は出ない）。"""
    p = prompts.build_evaluation_prompt()
    assert "# この商談の確定情報" not in p
    assert "出力フォーマット" in p


def test_prompt_asks_for_one_point():
    """改善の指示は one_point の1つに絞る（場面の指摘は絞らない）。"""
    p = prompts.build_evaluation_prompt()
    assert "one_point" in p
    assert "改善の指示（次にやること）は one_point の" in p


def test_roleplay_prompt_includes_planner_name():
    """1人ロープレでも練習者の氏名を確定情報として渡せる（当て字防止）。"""
    ctx = build_meeting_context("", "安栗実沙")
    p = prompts.build_roleplay_prompt(["まだ何も考えてなくて"], meeting_context=ctx)
    assert "安栗実沙" in p
    assert "1人ロープレ" in p


def test_prompt_enforces_length_inline_in_json_schema():
    """分量の指定は、離れた節だけでなく JSON の各項目定義にも書く（効きやすいため）。"""
    p = prompts.build_evaluation_prompt()
    schema = p.split("# 出力フォーマット", 1)[1]
    assert "150字以内" in schema      # summary
    assert "60字以内" in schema       # johari.comment / one_point.keep
    # sales_comment は字数ではなく「3文の形」で縛る（短くすると場面と次の一言が落ちるため）
    assert "3つの短文" in schema
    assert "各40字以内" in schema


def test_prompt_allows_fixing_homophone_mishearings():
    """同音の聞き取り違いだけは文脈で直してよい、という指示が入っている。"""
    p = prompts.build_evaluation_prompt()
    assert "同音の聞き取り違い" in p
    assert "聞き取り不明" in p


def test_fills_customer_name_placeholders():
    """『〇〇様』のまま出たセリフを実名に直す（そのまま読み上げられるように）。"""
    data = {
        "one_point": {"action": "「〇〇様はどんな雰囲気がお好みですか？」"},
        "feedback": [{"after": "○○様、そちらは（お客様名）様のご希望どおりです"}],
    }
    got = fill_customer_placeholders(data, "矢野淳也様")
    assert got["one_point"]["action"] == "「矢野淳也様はどんな雰囲気がお好みですか？」"
    assert got["feedback"][0]["after"] == "矢野淳也様、そちらは矢野淳也様のご希望どおりです"


def test_placeholder_fill_does_not_guess_a_surname():
    """姓を推測しない（「佐々木」を「佐々」にするような誤りを避ける）。"""
    assert fill_customer_placeholders("〇〇様、こんにちは", "林様") == "林様、こんにちは"
    assert fill_customer_placeholders("〇〇様へ", "佐々木健太様") == "佐々木健太様へ"


def test_placeholder_fill_is_noop_without_customer():
    """お客様名が無いとき（1人ロープレ等）は何もしない。"""
    text = "〇〇様はいかがですか"
    assert fill_customer_placeholders(text, "") == text


def test_placeholder_fill_keeps_real_names():
    """実名で書けているセリフは触らない。"""
    text = "矢野様、いかがですか"
    assert fill_customer_placeholders(text, "矢野淳也様") == text


def test_prompt_forbids_placeholder_names():
    ctx = build_meeting_context("初回商談 L260722484601　矢野淳也様｜物件", "森谷淳美")
    p = prompts.build_evaluation_prompt(meeting_context=ctx)
    assert "プレースホルダは絶対に書かない" in p


def test_prompt_naming_rule_absent_without_customer():
    """お客様名が無い経路（1人ロープレ）では、その指示を出さない。"""
    p = prompts.build_evaluation_prompt(
        meeting_context=build_meeting_context("", "安栗実沙"))
    assert "プレースホルダ" not in p


def test_prompt_requires_a_speakable_line():
    """『次の一言』は口に出せるセリフに限る（自分への指示にしない）。"""
    p = prompts.build_evaluation_prompt()
    assert "口に出せるセリフ" in p
    assert "自分への指示" in p


def test_prompt_requires_full_meeting_coverage():
    """商談の前半だけで打ち切らせない指示が入っている。"""
    p = prompts.build_evaluation_prompt()
    assert "最後まで" in p
    assert "序盤" in p and "終盤" in p
    assert "全長に散っているか" in p


def test_prompt_does_not_cap_the_number_of_findings():
    """件数の上限で網羅性を犠牲にしない。"""
    p = prompts.build_evaluation_prompt()
    assert "3〜5件" not in p
    assert "0〜3件" not in p
    assert p.count("件数の上限なし") >= 2


def test_prompt_splits_the_recording_into_three_segments():
    """録画の長さを分単位で示し、区間ごとに件数を要求する。

    「全体に散らして」と文章で頼むだけでは効かず、実測で場面の指摘が冒頭4分に
    固まった（隠れたニーズは16分台まで出ていたのに）。区切りを数値で示す。
    """
    p = prompts.build_evaluation_prompt(duration_sec=17 * 60 + 20)
    assert "この録画は **17:20** あります" in p
    assert "序盤：00:00 〜 05:46" in p
    assert "中盤：05:46 〜 11:33" in p
    assert "終盤：11:33 〜 17:20" in p
    assert "最低2件" in p


def test_long_recordings_use_hours_in_the_segment_ranges():
    """1時間を超える録画は HH:MM:SS で区間を示す。"""
    p = prompts.build_evaluation_prompt(duration_sec=2 * 3600 + 30 * 60)
    assert "この録画は **2:30:00** あります" in p
    assert "序盤：00:00 〜 50:00" in p
    assert "終盤：1:40:00 〜 2:30:00" in p


def test_no_segment_block_without_a_duration():
    """長さが取れなかったときは、この節を出さない（嘘の区間を示さない）。"""
    assert "拾うべき時間帯" not in prompts.build_evaluation_prompt()
    assert "拾うべき時間帯" not in prompts.build_evaluation_prompt(duration_sec=0)
