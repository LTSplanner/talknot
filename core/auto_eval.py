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
    candidates: list[dict], done_case_ids: set[str], limit: int,
    evaluated_counts: dict[str, int] | None = None,
) -> list[dict]:
    """自動評価する候補を『担当者に均等・古い順・最大 limit 件』で返す。

    candidates の各要素は {planner, case_id, summary, start, start_date} を想定。
    - case_id が空のものは除外（案件と紐づかない予定は評価しない）。
    - done_case_ids に含まれる case_id は除外（二重評価の防止）。
    - 同じ case_id が複数あれば1件だけ残す（最も古いもの）。

    **担当者ごとに順番に取る**（ラウンドロビン）。以前は全員をまとめて古い順に
    並べていたため、古い商談を多く持つ人ばかり評価が進み、実際に
    「8件の人と2件の人」という偏りが出た。各自の中では古い順に処理する。

    evaluated_counts（担当者→これまでの評価済み件数）を渡すと、**少ない人から**
    順番を始める。これで全体が追いつく。

    純関数。入力リストは変更しない。
    """
    if limit <= 0:
        return []

    done = {_norm_case_id(c) for c in done_case_ids if _norm_case_id(c)}

    # 担当者ごとに、古い順の待ち行列を作る（案件番号の重複はここで落とす）。
    queues: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for c in sorted(candidates, key=_sort_key):
        cid = _norm_case_id(c.get("case_id", ""))
        if not cid or cid in done or cid in seen:
            continue
        seen.add(cid)
        queues.setdefault(c.get("planner", ""), []).append(c)

    # 評価済みが少ない人を先に。同数なら、待っている商談が古い人を先に。
    counts = evaluated_counts or {}
    order = sorted(
        queues,
        key=lambda p: (counts.get(p, 0), _sort_key(queues[p][0])),
    )

    selected: list[dict] = []
    while len(selected) < limit and any(queues[p] for p in order):
        for planner in order:
            if not queues[planner]:
                continue
            selected.append(queues[planner].pop(0))
            if len(selected) >= limit:
                break
    return selected
