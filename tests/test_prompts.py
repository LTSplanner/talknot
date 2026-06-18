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


def test_prompt_has_two_axis_fields():
    p = prompts.build_evaluation_prompt()
    for token in ["reference_score", "reference_comment", "sales_score", "sales_comment"]:
        assert token in p


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
