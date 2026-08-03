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


# 発言先頭の話者名接頭辞（例「安葉実沙:「…」」の "安葉実沙:"）を除去するための正規表現。
# 「」で始まる引用の直前にある短い "名前:" のみを対象にし、誤除去を避ける。
_SPEAKER_PREFIX = re.compile(r"^\s*[^「」\n]{1,16}[:：]\s*(?=「)")


def _strip_speaker(text: str) -> str:
    """before/after の先頭に付いた話者名（『◯◯:』）を取り除く。"""
    if not text:
        return text
    return _SPEAKER_PREFIX.sub("", text, count=1)


# 「」で囲まれた引用（emotion_note に書かれたお客様の言葉）を拾う。
_QUOTED = re.compile(r"[「『]([^」』]+)[」』]")
# 比較用に落とす記号・空白。表記ゆれで取り違えを見逃さないため広めに取る。
_NOISE = re.compile(r"[\s、。，．,.!！?？…‥・~〜ー\-—「」『』()（）\[\]【】]+")


def _norm_talk(text: str) -> str:
    """発言どうしを突き合わせるための正規化（記号・空白を除去）。"""
    return _NOISE.sub("", text or "")


def _is_customer_echo(before: str, customer_line: str, emotion_note: str) -> bool:
    """before がお客様の発言の写しになっていないかを判定する。

    Gemini は話者を取り違えることがあり、その場合 before に
    「営業が返した言葉」ではなく「お客様が言った言葉」がそのまま入る。
    customer_line と emotion_note 内の引用を照合して検出する。

    営業がお客様の言葉をオウム返しする（正当なヒアリング技術）ケースを
    誤検出しないよう、ほぼ全文が一致するときだけ真とする。
    """
    b = _norm_talk(before)
    if len(b) < 6:  # 「はい」等の短い相槌は判定材料にならない
        return False

    candidates = [_norm_talk(customer_line)]
    candidates += [_norm_talk(q) for q in _QUOTED.findall(emotion_note or "")]

    for c in candidates:
        if len(c) < 6:
            continue
        if b == c:
            return True
        # before がお客様の発言の一部を切り出しただけ
        if b in c and len(b) / len(c) >= 0.6:
            return True
        # before がお客様の発言に一言足しただけ
        if c in b and len(c) / len(b) >= 0.8:
            return True
    return False


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
class CustomerProfile:
    """トーク全体から読み取ったお客様の『攻略メモ』（次回の活かし方）。

    決めつけではなく“傾向”として、意思決定・話し方の好みと、次回どう提案すると
    響くかをまとめる。過去データには無いため EvaluationResult では任意項目。
    """
    attributes: list[str] = field(default_factory=list)  # 特徴タグ（せっかち/慎重 等）1〜4個
    summary: str = ""        # 人物像の要約（意思決定・話し方の傾向）
    next_approach: str = ""  # 次回このお客様にどう提案すると響くか（効く言い回し・順番・避けること）


@dataclass
class OnePoint:
    """この商談で『次に直す1点』だけを絞り込んだアドバイス。

    点数・ジョハリ・シーン別フィードバックまで全部読むと何をすればいいか分からなく
    なるため、結果画面の一番上でこれだけを大きく見せる。詳細は下に畳んでおく。
    過去データには無いため EvaluationResult では任意項目。
    """
    headline: str = ""    # 直す1点の見出し（20字程度・行動で書く）
    timestamp: str = ""   # そう判断した代表的な場面 "MM:SS"
    reason: str = ""      # なぜそこか（その結果お客様がどうなったか）1〜2文
    action: str = ""      # 次回そのまま使える具体的な一言（セリフ）
    keep: str = ""        # 逆に、続けてほしい良かった点1つ


@dataclass
class TimestampedFeedback:
    """『動画の何分何秒のトーク』単位の Before/After フィードバック。"""
    timestamp: str          # "MM:SS"
    criterion_key: str      # どの評価項目に関わるか
    emotion_note: str       # その瞬間のお客様の感情の動き（トーン・間から）
    before: str             # 【営業担当】が実際に話したトーク（空＝特定できなかった）
    after: str              # こう言うべきだった、の具体例
    customer_line: str = ""  # きっかけになったお客様の発言（before との取り違え検出に使う）


@dataclass
class EvaluationResult:
    scores: list[CriterionScore] = field(default_factory=list)
    johari: "JohariAllocation | None" = None  # 会話配分（ジョハリの窓）
    hidden_needs: list[HiddenNeed] = field(default_factory=list)  # 隠れたニーズ（秘密領域）
    feedback: list[TimestampedFeedback] = field(default_factory=list)
    summary: str = ""        # 全体講評（ポジティブな振り返り）
    knowledge: list[KnowledgeItem] = field(default_factory=list)  # 抽出した弊社ナレッジ
    customer_profile: "CustomerProfile | None" = None  # お客様の攻略メモ（次回の活かし方）
    one_point: "OnePoint | None" = None  # 次に直す1点（結果画面の最上部に出す要約）

    @property
    def total(self) -> int:
        """後方互換の総合スコア（営業プロ視点の合計）。"""
        return self.sales_total

    @property
    def sales_total(self) -> int:
        return sum(s.sales_score for s in self.scores)

    @property
    def overall_total(self) -> int:
        """総合スコアの合計（1軸化後の呼称。sales_total のエイリアス）。"""
        return self.sales_total

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

    @staticmethod
    def _parse_feedback(f: dict) -> "TimestampedFeedback":
        """1件の Before/After を組み立てる。話者の取り違えはここで止める。

        before がお客様の発言の写しになっていたら、それは営業のトークではないので
        before を空にし（＝UI では「特定できなかった」と表示）、お客様の言葉は
        customer_line に寄せる。作り話で埋めないことを優先する。
        """
        emotion_note = f.get("emotion_note", "")
        customer_line = _strip_speaker(f.get("customer_line", ""))
        before = _strip_speaker(f.get("before", ""))

        if _is_customer_echo(before, customer_line, emotion_note):
            if not customer_line:
                customer_line = before
            before = ""

        return TimestampedFeedback(
            timestamp=f.get("timestamp", ""),
            criterion_key=f.get("criterion_key", ""),
            emotion_note=emotion_note,
            before=before,
            after=_strip_speaker(f.get("after", "")),
            customer_line=customer_line,
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

        customer_profile = None
        cp = data.get("customer_profile")
        if isinstance(cp, dict):
            raw_attrs = cp.get("attributes")
            attrs = (
                [str(a) for a in raw_attrs if str(a).strip()]
                if isinstance(raw_attrs, list)
                else []
            )
            customer_profile = CustomerProfile(
                attributes=attrs,
                summary=cp.get("summary") or "",
                next_approach=cp.get("next_approach") or "",
            )

        one_point = None
        op = data.get("one_point")
        if isinstance(op, dict) and (op.get("headline") or op.get("action")):
            one_point = OnePoint(
                headline=op.get("headline") or "",
                timestamp=op.get("timestamp") or "",
                reason=op.get("reason") or "",
                action=_strip_speaker(op.get("action") or ""),
                keep=op.get("keep") or "",
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
            feedback=[cls._parse_feedback(f) for f in data.get("feedback", [])],
            summary=data.get("summary", ""),
            knowledge=[
                KnowledgeItem(
                    category=k.get("category", ""),
                    point=k.get("point", ""),
                )
                for k in data.get("knowledge", [])
                if k.get("point")
            ],
            customer_profile=customer_profile,
            one_point=one_point,
        )

    def to_dict(self) -> dict:
        return {
            "scores": [vars(s) for s in self.scores],
            "johari": vars(self.johari) if self.johari else None,
            "hidden_needs": [vars(h) for h in self.hidden_needs],
            "feedback": [vars(f) for f in self.feedback],
            "summary": self.summary,
            "knowledge": [vars(k) for k in self.knowledge],
            "customer_profile": vars(self.customer_profile) if self.customer_profile else None,
            "one_point": vars(self.one_point) if self.one_point else None,
        }
