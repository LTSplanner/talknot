"""Gemini へ渡す評価プロンプトの組み立て。

評価項目は config.settings.EVALUATION_CRITERIA を唯一の真実として参照する。
出力は core.models.EvaluationResult と対応する JSON に固定する。
"""
from __future__ import annotations

from config import settings


def build_evaluation_prompt(
    reference_talk: str | None = None,
    knowledge_base: str | None = None,
) -> str:
    criteria_lines = "\n".join(
        f"- {c.key} ({c.number} {c.title}): {c.description}"
        for c in settings.EVALUATION_CRITERIA
    )
    reference_block = (
        f"\n# 模範トーク（社内基準）\n{reference_talk}\n" if reference_talk else ""
    )
    knowledge_block = (
        "\n# 弊社ナレッジ（過去の商談から蓄積した社内知識。これを前提に評価する）\n"
        f"{knowledge_base}\n"
        if knowledge_base
        else ""
    )
    reference_axis_note = (
        "reference（🎯 模範トーク視点）は、上の『模範トーク』と比べてどれだけ近づけたかで採点する。"
        if reference_talk
        else "reference（🎯 模範トーク視点）は、住宅営業トップの理想トークを基準に、どれだけ近いかで採点する（模範トーク未登録のため理想像を基準にする）。"
    )
    return f"""{settings.SALES_AI_PERSONA}

動画（または音声）から、文字面だけでなく「声のトーン」「間」「発話比率」を手がかりに、
お客様の感情の動きを読み取ってください。批判ではなく、会話がもっと弾むための
ポジティブな振り返りを行います。
{reference_block}{knowledge_block}
# 評価の2軸（各項目を、必ず次の2つの視点それぞれで 1〜5 段階で採点する）
- reference（🎯 模範トーク視点）：{settings.AXES_BY_KEY['reference'].description}
- sales（💼 営業プロ視点）：{settings.AXES_BY_KEY['sales'].description}
{reference_axis_note}

# 評価項目
{criteria_lines}

# 出力フォーマット（JSON のみ。前後に説明文を付けない）
{{
  "scores": [{{
    "key": "<上記key>",
    "reference_score": <1-5>,
    "reference_comment": "<模範トーク視点での講評（近い点・差分・学ぶ点）>",
    "sales_score": <1-5>,
    "sales_comment": "<営業プロ視点での講評（できている点・次の一手）>"
  }}],
  "feedback": [{{
    "timestamp": "MM:SS",
    "criterion_key": "<関連する評価項目key>",
    "emotion_note": "<その瞬間のお客様の感情の動き>",
    "before": "<実際のトーク。感情をスルーしていた箇所>",
    "after": "<本来こう言うべきだった、の具体的な改善トーク例>"
  }}],
  "summary": "<2軸を踏まえた全体のポジティブな振り返り>",
  "knowledge": [{{
    "category": "<product=商品知識 / rule=社内ルール / technique=トーク技術 のいずれか>",
    "point": "<この商談から学べる、他の商談にも使える一般的な知識・ルール・コツ>"
  }}]
}}

各項目について reference と sales の両方のスコア・講評を必ず出してください。
feedback は必ず動画内の具体的なタイムスタンプ付きで、Before/After をセットで出してください。

knowledge には、この商談から抽出できる『弊社の財産になる知識』を 0〜5 件入れてください。
- product（商品知識）/ rule（社内ルール）/ technique（トーク技術）の3カテゴリで、学びがあるものだけ。
- 必ず一般化して書く（次の商談でも使える形に）。特筆すべき学びが無ければ空配列 [] でよい。
- 個人情報は絶対に含めない（顧客名・住所・電話番号・金額などの個別具体情報は書かない）。"""
