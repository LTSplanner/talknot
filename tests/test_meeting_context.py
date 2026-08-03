"""商談の確定情報（予定タイトルの解析とプロンプト反映）のテスト。"""
from core import prompts
from core.meeting_context import build_meeting_context, known_names, parse_meeting_title


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


def test_prompt_asks_for_one_point_and_short_output():
    """1ポイントアドバイスと、絞った件数の指示が入っている。"""
    p = prompts.build_evaluation_prompt()
    assert "one_point" in p
    assert "3〜5件" in p


def test_roleplay_prompt_includes_planner_name():
    """1人ロープレでも練習者の氏名を確定情報として渡せる（当て字防止）。"""
    ctx = build_meeting_context("", "安栗実沙")
    p = prompts.build_roleplay_prompt(["まだ何も考えてなくて"], meeting_context=ctx)
    assert "安栗実沙" in p
    assert "1人ロープレ" in p
