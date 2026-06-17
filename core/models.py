"""TalKnot の評価結果データモデル。

Gemini の出力もこの構造（JSON）に揃え、UI もこの構造を描画する。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CriterionScore:
    """評価項目ごとの 1〜5 段階スコア。key は settings.Criterion.key に対応。"""
    key: str
    score: int          # 1〜5
    comment: str        # ポジティブな講評


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
        return sum(s.score for s in self.scores)

    def score_for(self, key: str) -> CriterionScore | None:
        return next((s for s in self.scores if s.key == key), None)

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationResult":
        """Gemini が返す JSON（core/prompts.py のフォーマット）からの復元。"""
        return cls(
            scores=[
                CriterionScore(
                    key=s.get("key", ""),
                    score=int(s.get("score", 0)),
                    comment=s.get("comment", ""),
                )
                for s in data.get("scores", [])
            ],
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
