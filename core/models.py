"""TalKnot の評価結果データモデル。

Gemini の出力もこの構造（JSON）に揃え、UI もこの構造を描画する。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CriterionScore:
    """評価項目ごとの 2軸スコア（各 1〜5 段階）。key は settings.Criterion.key に対応。

    🎯 reference（模範トーク視点）と 💼 sales（営業プロ視点）の2軸で採点する。
    """
    key: str
    reference_score: int    # 🎯 模範トーク視点 1〜5
    reference_comment: str  # 模範と比べた講評
    sales_score: int        # 💼 営業プロ視点 1〜5
    sales_comment: str      # 営業プロ視点の講評

    @property
    def score(self) -> int:
        """後方互換：単一スコアが要る箇所では営業プロ視点を代表値とする。"""
        return self.sales_score

    @property
    def comment(self) -> str:
        return self.sales_comment


@dataclass
class TimestampedFeedback:
    """『動画の何分何秒のトーク』単位の Before/After フィードバック。"""
    timestamp: str          # "MM:SS"
    criterion_key: str      # どの評価項目に関わるか
    emotion_note: str       # その瞬間のお客様の感情の動き（トーン・間から）
    before: str             # 実際のトーク（感情をスルーしていた箇所）
    after: str              # こう言うべきだった、の具体例


@dataclass
class EvaluationResult:
    scores: list[CriterionScore] = field(default_factory=list)
    feedback: list[TimestampedFeedback] = field(default_factory=list)
    summary: str = ""        # 全体講評（ポジティブな振り返り）

    @property
    def total(self) -> int:
        """後方互換の総合スコア（営業プロ視点の合計）。"""
        return self.sales_total

    @property
    def sales_total(self) -> int:
        return sum(s.sales_score for s in self.scores)

    @property
    def reference_total(self) -> int:
        return sum(s.reference_score for s in self.scores)

    def score_for(self, key: str) -> CriterionScore | None:
        return next((s for s in self.scores if s.key == key), None)

    @staticmethod
    def _parse_score(s: dict) -> CriterionScore:
        """2軸スコアを復元。旧 score/comment 形式しか無い場合は両軸に流用する。"""
        def _int(v) -> int:
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0

        return CriterionScore(
            key=s.get("key", ""),
            reference_score=_int(s.get("reference_score", s.get("score", 0))),
            reference_comment=s.get("reference_comment", s.get("comment", "")),
            sales_score=_int(s.get("sales_score", s.get("score", 0))),
            sales_comment=s.get("sales_comment", s.get("comment", "")),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationResult":
        """Gemini が返す JSON（core/prompts.py のフォーマット）からの復元。"""
        return cls(
            scores=[cls._parse_score(s) for s in data.get("scores", [])],
            feedback=[
                TimestampedFeedback(
                    timestamp=f.get("timestamp", ""),
                    criterion_key=f.get("criterion_key", ""),
                    emotion_note=f.get("emotion_note", ""),
                    before=f.get("before", ""),
                    after=f.get("after", ""),
                )
                for f in data.get("feedback", [])
            ],
            summary=data.get("summary", ""),
        )

    def to_dict(self) -> dict:
        return {
            "scores": [vars(s) for s in self.scores],
            "feedback": [vars(f) for f in self.feedback],
            "summary": self.summary,
        }
