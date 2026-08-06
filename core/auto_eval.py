"""初回商談の自動評価バッチの純ロジック（外部I/Oなし・テスト対象）。

カレンダーの商談予定（services.google_calendar.list_meetings の返り値相当）から
「初回商談だけ」を抽出し、まだ評価していないものを『古い順・1日◯件まで』に
絞り込むための純関数を提供する。ネットワーク・ファイル等の副作用は一切持たない。

呼び出し側（scripts/auto_evaluate_meetings.py）が、ここで選ばれた候補に対して
録画照合・ダウンロード・Gemini評価・保存という副作用を行う。
"""
from __future__ import annotations

import re

# 予定タイトルが「初回商談」であることを示す語（これを含むものだけ自動評価する）。
_FIRST_MEETING_KEYWORD = "初回"

# 「初回仕様MT」など仕様の打ち合わせは自動評価しない。
# タイトルに「初回」が入るため以前は対象に混ざっていたが、商談ではなく
# 仕様を詰める打合せなので、営業トークの評価軸に合わない。
_EXCLUDE_KEYWORDS = ("仕様",)

# SR（ショールーム）での対面商談も対象外。オンライン商談と条件が違うため。
# 「SRC造」のように他の語の一部と一致しないよう、独立した語のときだけ弾く。
_EXCLUDE_TOKEN_RE = re.compile(r"(?<![A-Za-z])SR(?![A-Za-z])")

# 案件番号（例: L260721484101）。全角Ｌ・間の空白も許容。google_calendar と同じ形。
_CASE_ID_RE = re.compile(r"[LＬ]\s*\d{6,}")


def is_first_meeting(summary: str) -> bool:
    """予定タイトルが自動評価の対象（初回商談）か。

    「初回」を含み、かつ「仕様」「SR」を含まないものだけを対象にする。
    - 「初回仕様MT」は初回だが、商談ではなく仕様を詰める打合せなので除外。
    - 「SR」はショールームでの対面商談。オンライン商談と条件が違うので除外。

    案件番号（L付き）かどうかは list_meetings 側（deals_only）で既に絞られている想定。
    """
    text = summary or ""
    if any(w in text for w in _EXCLUDE_KEYWORDS):
        return False
    if _EXCLUDE_TOKEN_RE.search(text):
        return False
    return _FIRST_MEETING_KEYWORD in text


def _norm_case_id(case_id: str) -> str:
    """案件番号を比較用に正規化する（空白を除去）。空なら空文字。"""
    return re.sub(r"\s", "", case_id or "")


# 同じ案件で失敗が何回まで続いたら諦めるか。無料枠の枠切れ(429)は待てば直るので
# 再挑戦したいが、内容の問題で必ず失敗する商談を毎日引き続けても意味がない。
MAX_RETRY_ON_ERROR = 3


def done_case_ids(records: list[dict]) -> set[str]:
    """再評価しなくてよい案件番号を返す。

    - 成功(done)した案件は完了とみなす。
    - 失敗(error)は**再挑戦の対象**にする。無料枠の枠切れで落ちた商談を
      永久に取りこぼさないため。ただし同じ案件で MAX_RETRY_ON_ERROR 回
      失敗していたら、内容の問題とみなして諦める。
    - 解析中(processing)は二重に走らせない。
    """
    done: set[str] = set()
    failures: dict[str, int] = {}
    for rec in records or []:
        ids = case_ids_in(rec.get("label", ""))
        status = rec.get("status", "done")
        if status == "error":
            for cid in ids:
                failures[cid] = failures.get(cid, 0) + 1
        else:
            done |= ids
    done |= {cid for cid, n in failures.items() if n >= MAX_RETRY_ON_ERROR}
    return done


def case_ids_in(text: str) -> set[str]:
    """テキスト（評価履歴の label 等）に含まれる案件番号を正規化して返す。

    保存済み評価の label（＝予定タイトル）から案件番号を拾い、二重評価の判定に使う。
    """
    return {_norm_case_id(m.group()) for m in _CASE_ID_RE.finditer(text or "")}


def _sort_key(candidate: dict) -> str:
    """並べ替えキー：start（日時）を優先し、無ければ start_date（日付）。"""
    return str(candidate.get("start") or candidate.get("start_date") or "")


def select_targets(
    candidates: list[dict], done_case_ids: set[str], limit: int
) -> list[dict]:
    """自動評価する候補を『古い順・最大 limit 件』に絞って返す。

    candidates の各要素は {planner, case_id, summary, start, start_date} を想定。
    - case_id が空のものは除外（案件と紐づかない予定は評価しない）。
    - done_case_ids（正規化済み案件番号）に含まれる case_id は除外（二重評価/無限リトライ防止）。
    - 同じ case_id が複数あれば1件だけ残す（最も古いもの）。
    - start（無ければ start_date）の昇順＝古い順で最大 limit 件を返す。

    純関数。入力リストは変更しない。
    """
    if limit <= 0:
        return []

    # 古い順に並べてから、案件番号で重複排除（最初＝最も古い1件を残す）。
    ordered = sorted(candidates, key=_sort_key)
    done = {_norm_case_id(c) for c in done_case_ids if _norm_case_id(c)}

    selected: list[dict] = []
    seen: set[str] = set()
    for c in ordered:
        cid = _norm_case_id(c.get("case_id", ""))
        if not cid:
            continue
        if cid in done or cid in seen:
            continue
        seen.add(cid)
        selected.append(c)
        if len(selected) >= limit:
            break
    return selected
