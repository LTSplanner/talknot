"""Gemini プロンプト組み立てのテスト。"""
from config import settings
from core import prompts


def test_prompt_includes_all_criteria_keys():
    p = prompts.build_evaluation_prompt()
    for c in settings.EVALUATION_CRITERIA:
        assert c.key in p
        assert c.title in p


def test_prompt_requires_timestamped_before_after():
    p = prompts.build_evaluation_prompt()
    for token in ["MM:SS", "before", "after", "timestamp", "emotion_note"]:
        assert token in p


def test_prompt_forces_japanese_output():
    p = prompts.build_evaluation_prompt()
    assert "日本語で書いて" in p and "英語を混ぜない" in p


def test_prompt_requests_hidden_needs_and_strict_scoring():
    p = prompts.build_evaluation_prompt()
    # 隠れたニーズ（秘密領域）の出力フィールド
    for token in ["hidden_needs", "signal", "inferred_need", "surfaced", "秘密領域"]:
        assert token in p
    # 厳格採点のアンカー（甘い点を付けない方針）
    for token in ["甘い", "2〜3", "非言語"]:
        assert token in p


def test_prompt_has_two_axis_fields():
    p = prompts.build_evaluation_prompt()
    for token in ["reference_score", "reference_comment", "sales_score", "sales_comment"]:
        assert token in p


def test_prompt_axes_are_differentiated():
    """2軸が別の物差しで、同点にしないよう指示しているか。"""
    p = prompts.build_evaluation_prompt()
    for token in ["別の物差し", "再現度", "本質的な質", "同じ数字にしない"]:
        assert token in p


def test_reference_axis_note_changes_with_reference_talk():
    with_ref = prompts.build_evaluation_prompt(reference_talk="模範です")
    without = prompts.build_evaluation_prompt()
    assert "再現できたか" in with_ref       # 登録模範トークの再現度
    assert "基本の型" in without            # 未登録時は基本の型が基準


def test_prompt_uses_sales_persona():
    p = prompts.build_evaluation_prompt()
    assert settings.SALES_AI_PERSONA[:20] in p


def test_reference_talk_is_embedded_when_given():
    p = prompts.build_evaluation_prompt("これが模範トークです")
    assert "これが模範トークです" in p
    assert "模範トーク" in p


def test_no_reference_block_when_absent():
    p = prompts.build_evaluation_prompt()
    assert "# 模範トーク（社内基準）" not in p


def test_prompt_requests_knowledge_extraction():
    p = prompts.build_evaluation_prompt()
    for token in ["knowledge", "category", "point", "個人情報"]:
        assert token in p


def test_knowledge_base_injected_when_given():
    p = prompts.build_evaluation_prompt(knowledge_base="【商品知識】\n- ZEH仕様は補助金対象")
    assert "弊社ナレッジ" in p
    assert "ZEH仕様は補助金対象" in p


def test_no_knowledge_block_when_absent():
    p = prompts.build_evaluation_prompt()
    assert "# 弊社ナレッジ" not in p
