"""KNOTE の評価結果データモデル。

Gemini の出力もこの構造（JSON）に揃え、UI もこの構造を描画する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 評価文でAIが英語のジョハリ用語（Open/Blind/Hidden/Unknown）を混ぜることがあるため、
# 解析時に日本語（開放/盲点/秘密/未知 領域）へ統一する。過去に保存した評価も表示時に直る。
_JA_JOHARI_SUBS = [
    # 「English（開放/盲点/秘密/未知[領域]）」→ 日本語だけにする
    (re.compile(r"[A-Za-z]+\s*[（(]\s*(開放|盲点|秘密|未知)\s*領域?\s*[）)]"), r"\1領域"),
    # 「English領域」→ 日本語領域（大文字小文字問わず）
    (re.compile(r"(?i)hidden\s*領域"), "秘密領域"),
    (re.compile(r"(?i)blind\s*領域"), "盲点領域"),
    (re.compile(r"(?i)open\s*領域"), "開放領域"),
    (re.compile(r"(?i)unknown\s*領域"), "未知領域"),
]


def _ja_johari(text: str) -> str:
    if not text:
        return text
    for pat, rep in _JA_JOHARI_SUBS:
        text = pat.sub(rep, text)
    return text


def _deep_ja_johari(obj):
    """dict/list を再帰的にたどり、文字列値のジョハリ英語表記を日本語へ置換する。"""
    if isinstance(obj, str):
        return _ja_johari(obj)
    if isinstance(obj, dict):
        return {k: _deep_ja_johari(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_ja_johari(v) for v in obj]
    return obj


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
class KnowledgeItem:
    """商談から抽出した弊社ナレッジの1項目（個人情報は含めない）。"""
    category: str   # product（商品知識）/ rule（社内ルール）/ technique（トーク技術）
    point: str      # 一般化した知識・ルール・コツ（顧客名・住所などは含めない）


@dataclass
class JohariAllocation:
    """商談の会話時間を『ジョハリの窓』4領域に配分した割合（合計≒100）。

    良い商談は、開放領域（既知の確認）だけでなく、盲点領域（プロからの提案・気づき）と
    秘密領域（お客様の本音・事情の引き出し）に時間を割けている。
    """
    open_pct: int      # 開放領域：双方が知っている（既知の確認）
    blind_pct: int     # 盲点領域：お客様が気づいていない（プロの提案・気づき）
    hidden_pct: int    # 秘密領域：お客様の本音・事情（引き出すべき）
    unknown_pct: int   # 未知領域：双方が知らない（対話で新発見）
    comment: str       # 配分の講評（盲点・秘密にもっと時間を割くには等）

    @property
    def value_pct(self) -> int:
        """価値創出ゾーン（盲点＋秘密）の割合。"""
        return self.blind_pct + self.hidden_pct


@dataclass
class HiddenNeed:
    """お客様が言葉にしていない『隠れたニーズ（秘密領域）』の1項目。

    非言語サイン（間・トーン・言い淀み・話題回避・過剰同意など）を根拠に、
    お客様自身も自覚していない不安・疑問・本音を推定し、営業が踏み込めたかを見る。
    """
    timestamp: str          # "MM:SS"
    signal: str             # 根拠となった非言語サイン
    inferred_need: str      # 言葉にされていない不安・疑問・本音
    surfaced: bool          # 営業がそれに気づき踏み込めたか
    note: str               # 踏み込めた点 / 本来どう触れるべきだったか


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
    johari: "JohariAllocation | None" = None  # 会話配分（ジョハリの窓）
    hidden_needs: list[HiddenNeed] = field(default_factory=list)  # 隠れたニーズ（秘密領域）
    feedback: list[TimestampedFeedback] = field(default_factory=list)
    summary: str = ""        # 全体講評（ポジティブな振り返り）
    knowledge: list[KnowledgeItem] = field(default_factory=list)  # 抽出した弊社ナレッジ

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
        # 英語のジョハリ用語（Hidden領域 等）を日本語（秘密領域 等）へ統一する
        data = _deep_ja_johari(data)

        def _bool(v) -> bool:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ("true", "1", "yes", "はい", "○")

        def _int(v) -> int:
            try:
                return int(float(v or 0))
            except (TypeError, ValueError):
                return 0

        johari = None
        j = data.get("johari")
        if isinstance(j, dict) and any(
            k in j for k in ("open_pct", "blind_pct", "hidden_pct", "unknown_pct")
        ):
            johari = JohariAllocation(
                open_pct=_int(j.get("open_pct")),
                blind_pct=_int(j.get("blind_pct")),
                hidden_pct=_int(j.get("hidden_pct")),
                unknown_pct=_int(j.get("unknown_pct")),
                comment=j.get("comment", ""),
            )

        return cls(
            scores=[cls._parse_score(s) for s in data.get("scores", [])],
            johari=johari,
            hidden_needs=[
                HiddenNeed(
                    timestamp=h.get("timestamp", ""),
                    signal=h.get("signal", ""),
                    inferred_need=h.get("inferred_need", ""),
                    surfaced=_bool(h.get("surfaced", False)),
                    note=h.get("note", ""),
                )
                for h in data.get("hidden_needs", [])
                if h.get("inferred_need")
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
            knowledge=[
                KnowledgeItem(
                    category=k.get("category", ""),
                    point=k.get("point", ""),
                )
                for k in data.get("knowledge", [])
                if k.get("point")
            ],
        )

    def to_dict(self) -> dict:
        return {
            "scores": [vars(s) for s in self.scores],
            "johari": vars(self.johari) if self.johari else None,
            "hidden_needs": [vars(h) for h in self.hidden_needs],
            "feedback": [vars(f) for f in self.feedback],
            "summary": self.summary,
            "knowledge": [vars(k) for k in self.knowledge],
        }
