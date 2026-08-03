"""商談の『確定情報』（誰の・どのお客様の・どの物件か）を組み立てる純ロジック。

カレンダーの予定タイトルは社内の書式で
    ◎初回商談 オンライン L260722484601　福島慶紀様｜朝霞市三原3丁目の新築マンション
のように、案件番号・お客様名・物件名を必ず含んでいる。営業担当の氏名も
Drive の表示名から確定できる。これらを Gemini に渡すことで、固有名詞を
**音声の聞き取りに頼らず正しい表記で書かせる**（例：「安栗」を音から
「アングルリ」と当て字にしてしまう誤りを防ぐ）。

外部I/Oは持たない（呼び出し側が氏名・タイトル・日付を渡す）。
"""
from __future__ import annotations

import re

# 案件番号（例: L260721484101）。全角Ｌ・間の空白も許容。google_calendar と同じ形。
_CASE_ID_RE = re.compile(r"[LＬ]\s*\d{6,}")

# お客様名と物件名の区切り（全角/半角の縦棒）。
_SEP_RE = re.compile(r"[｜|]")

# 案件番号が無いタイトルから、お客様名を拾うために取り除く一般語。
_GENERIC_WORDS = (
    "初回仕様MT", "初回商談", "仕様MT", "商談", "オンライン", "打合せ", "打ち合わせ",
    "面談", "定例", "MTG", "mtg", "SR", "◎", "★", "【", "】",
)


def _clean(text: str) -> str:
    """前後の空白（全角含む）を落とし、連続する空白を1つに詰める。"""
    return re.sub(r"\s+", " ", (text or "").replace("　", " ")).strip()


def parse_meeting_title(summary: str) -> dict:
    """予定タイトルから ``{case_id, customer_name, property_name}`` を取り出す。

    案件番号の**後ろ**を「お客様名｜物件名」とみなす（社内書式）。区切りが無ければ
    全体をお客様名として扱う。案件番号が無いタイトルでは、先に一般語（初回商談・
    オンライン等）を除いてからお客様名を拾う。

    取れなかった項目は空文字を返す（呼び出し側で「不明」として扱えるように）。
    """
    s = (summary or "").strip()

    m = _CASE_ID_RE.search(s)
    if m:
        case_id = re.sub(r"\s", "", m.group())
        rest = s[m.end():]
    else:
        case_id = ""
        rest = s
        for w in _GENERIC_WORDS:
            rest = rest.replace(w, " ")

    parts = _SEP_RE.split(rest, 1)
    return {
        "case_id": case_id,
        "customer_name": _clean(parts[0]),
        "property_name": _clean(parts[1]) if len(parts) > 1 else "",
    }


def build_meeting_context(
    summary: str, planner_name: str = "", meeting_date: str = ""
) -> dict:
    """予定タイトル＋営業担当名＋実施日から、Gemini に渡す確定情報を組み立てる。

    planner_name は services.google_drive.get_display_name() で取れる氏名を想定。
    取れていない（空）場合はそのキーを落とし、プロンプト側で「不明」として扱う。
    """
    ctx = parse_meeting_title(summary)
    ctx["planner_name"] = _clean(planner_name)
    ctx["meeting_date"] = _clean(meeting_date)
    return ctx


# セリフに残ってしまう「お客様名の空欄」。そのままでは読み上げられない。
_PLACEHOLDER_RE = re.compile(
    r"[（(]?(?:〇〇|○○|◯◯|△△|××|XX|xx|ＸＸ|お客様名|顧客名)[）)]?\s*(?=様)"
)


def fill_customer_placeholders(obj, customer_name: str):
    """評価結果の中の「〇〇様」を、確定しているお客様の姓＋様に置き換える。

    プロンプトでも実名で書くよう指示しているが、モデルは実行ごとにブレて
    プレースホルダのまま出すことがある。改善案のセリフ（after / one_point.action）は
    そのまま口に出せることが価値なので、コード側でも直す。

    置き換えるのは**確定情報の表記そのまま**（例「矢野淳也様」）。姓だけを取ろうと
    すると「佐々木」を「佐々」にしてしまうなど誤りが起きるため、推測はしない。
    """
    name = _clean(customer_name).rstrip("様")
    if not name:
        return obj

    def _fix(text: str) -> str:
        return _PLACEHOLDER_RE.sub(name, text)

    def _walk(o):
        if isinstance(o, str):
            return _fix(o)
        if isinstance(o, dict):
            return {k: _walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_walk(v) for v in o]
        return o

    return _walk(obj)


def known_names(context: dict | None) -> list[str]:
    """確定情報に含まれる『正しい表記の固有名詞』を列挙する（プロンプト用）。"""
    if not isinstance(context, dict):
        return []
    keys = ("planner_name", "customer_name", "property_name")
    return [v for v in (_clean(context.get(k, "")) for k in keys) if v]
