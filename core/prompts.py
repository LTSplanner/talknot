"""Gemini へ渡す評価プロンプトの組み立て。

評価項目は config.settings.EVALUATION_CRITERIA を唯一の真実として参照する。
出力は core.models.EvaluationResult と対応する JSON に固定する。
"""
from __future__ import annotations

from config import settings


def build_evaluation_prompt(reference_talk: str | None = None) -> str:
    criteria_lines = "\n".join(
        f"- {c.key} ({c.number} {c.title}): {c.description}"
        for c in settings.EVALUATION_CRITERIA
    )
    reference_block = (
        f"\n# 模範トーク（社内基準）\n{reference_talk}\n" if reference_talk else ""
    )
    return f"""あなたは住宅営業の商談・ロープレを評価するベテランコーチです。
動画（または音声）から、文字面だけでなく「声のトーン」「間」「発話比率」を手がかりに、
お客様の感情の動きを読み取ってください。批判ではなく、会話がもっと弾むための
ポジティブな振り返りを行います。
{reference_block}
# 評価項目（各 1〜5 段階）
{criteria_lines}

# 出力フォーマット（JSON のみ。前後に説明文を付けない）
{{
  "scores": [{{"key": "<上記key>", "score": <1-5>, "comment": "<ポジティブな講評>"}}],
  "feedback": [{{
    "timestamp": "MM:SS",
    "criterion_key": "<関連する評価項目key>",
    "emotion_note": "<その瞬間のお客様の感情の動き>",
    "before": "<実際のトーク。感情をスルーしていた箇所>",
    "after": "<本来こう言うべきだった、の具体的な改善トーク例>"
  }}],
  "summary": "<全体のポジティブな振り返り>"
}}

feedback は必ず動画内の具体的なタイムスタンプ付きで、Before/After をセットで出してください。"""
