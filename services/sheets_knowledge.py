"""弊社ナレッジを Google スプレッドシートに永続保存するバックエンド。

共有ドライブのスプレッドシート（settings.KNOWLEDGE_SHEET_ID）に、最小権限の
サービスアカウントで読み書きする。人もシートを直接開いて閲覧・編集できる。

設定が無いときは configured() が False を返し、storage.py 側がローカル保存に
フォールバックする（ローカル開発・テスト時はこちらは一切呼ばれない）。

シートの形式（1 行目はヘッダー）:
    A: category（product / rule / technique）
    B: point（知識本文）
    C: added_at（登録日時の文字列）
"""
from __future__ import annotations

import json
import time

from config import settings

_HEADER = ["category", "point", "added_at"]


def _cfg(name: str) -> str:
    """settings から安全に取得（再デプロイ移行期に属性が無くても落ちないように）。"""
    return getattr(settings, name, "") or ""


def configured() -> bool:
    """スプレッドシート保存が使える設定がそろっているか。"""
    return bool(_cfg("KNOWLEDGE_SHEET_ID")) and bool(
        _cfg("KNOWLEDGE_SA_JSON") or _cfg("KNOWLEDGE_SA_FILE")
    )


def _service():
    """Sheets API クライアントを返す（依存は遅延 import）。"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = getattr(settings, "SHEETS_SCOPES", None) or [
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    if _cfg("KNOWLEDGE_SA_JSON"):
        info = json.loads(_cfg("KNOWLEDGE_SA_JSON"))
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            _cfg("KNOWLEDGE_SA_FILE"), scopes=scopes
        )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _tab() -> str:
    return _cfg("KNOWLEDGE_SHEET_TAB") or "Knowledge"


_REFERENCE_TAB = "Reference"
_REFERENCE_HEADER = ["id", "label", "status", "text", "added_at"]


def _ensure_tab(svc, title: str, sheet_id: str | None = None) -> None:
    """シートに指定タブが無ければ作る。"""
    sid = sheet_id or _cfg("KNOWLEDGE_SHEET_ID")
    meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if title not in titles:
        svc.spreadsheets().batchUpdate(
            spreadsheetId=sid,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()


# --------------------------------------------------------------------------- #
# 評価履歴（各自のみ閲覧。アプリ側で user_email により絞り込む）
# --------------------------------------------------------------------------- #
_EVAL_TAB = "Evaluations"
_EVAL_HEADER = ["job_id", "user_email", "saved_at", "status", "label", "result_json", "error"]


def _eval_sheet_id() -> str:
    return _cfg("EVALUATIONS_SHEET_ID") or _cfg("KNOWLEDGE_SHEET_ID")


def load_evaluations() -> list[dict]:
    """Evaluations タブの全行を返す（フィルタは呼び出し側）。"""
    svc = _service()
    try:
        resp = (
            svc.spreadsheets()
            .values()
            .get(spreadsheetId=_eval_sheet_id(), range=f"{_EVAL_TAB}!A2:G")
            .execute()
        )
    except Exception:
        return []
    out: list[dict] = []
    for row in resp.get("values", []):
        def c(i: int) -> str:
            return (row[i] if len(row) > i else "").strip()

        if not c(0):
            continue
        out.append({
            "job_id": c(0),
            "user_email": c(1),
            "saved_at": c(2),
            "status": c(3) or "done",
            "label": c(4),
            "result_json": c(5),
            "error": c(6),
        })
    return out


def save_evaluations(items: list[dict]) -> None:
    """Evaluations タブを全置換で書き戻す（タブが無ければ作る）。"""
    svc = _service()
    sid = _eval_sheet_id()
    _ensure_tab(svc, _EVAL_TAB, sheet_id=sid)
    svc.spreadsheets().values().clear(
        spreadsheetId=sid, range=f"{_EVAL_TAB}!A:G"
    ).execute()
    values = [_EVAL_HEADER] + [
        [
            it.get("job_id", ""),
            it.get("user_email", ""),
            it.get("saved_at", ""),
            it.get("status", "done"),
            it.get("label", ""),
            it.get("result_json", ""),
            it.get("error", ""),
        ]
        for it in items
    ]
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"{_EVAL_TAB}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def load_reference() -> list[dict]:
    """Reference タブから模範トークを読む（id/label/status/text/added_at）。"""
    svc = _service()
    try:
        resp = (
            svc.spreadsheets()
            .values()
            .get(
                spreadsheetId=_cfg("KNOWLEDGE_SHEET_ID"),
                range=f"{_REFERENCE_TAB}!A2:E",
            )
            .execute()
        )
    except Exception:
        return []
    items: list[dict] = []
    for row in resp.get("values", []):
        def cell(i: int) -> str:
            return (row[i] if len(row) > i else "").strip()

        text = cell(3)
        item = {
            "id": cell(0),
            "label": cell(1),
            "status": cell(2) or "done",
            "text": text,
        }
        if cell(4):
            item["added_at"] = cell(4)
        items.append(item)
    return items


def save_reference(items: list[dict]) -> None:
    """Reference タブを全置換で書き戻す（タブが無ければ作る）。"""
    svc = _service()
    _ensure_tab(svc, _REFERENCE_TAB)
    sid = _cfg("KNOWLEDGE_SHEET_ID")
    svc.spreadsheets().values().clear(
        spreadsheetId=sid, range=f"{_REFERENCE_TAB}!A:E"
    ).execute()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    values = [_REFERENCE_HEADER] + [
        [
            it.get("id", ""),
            it.get("label", ""),
            it.get("status", "done"),
            it.get("text", ""),
            it.get("added_at", now),
        ]
        for it in items
    ]
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"{_REFERENCE_TAB}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


# --------------------------------------------------------------------------- #
# 社内ナレッジ資料（商品・料金・サービス・FAQ などの整備済みテキスト）
# 1セル5万文字の上限があるため、複数行に分割して保存し、読み出し時に結合する。
# --------------------------------------------------------------------------- #
_DOC_TAB = "KnowledgeDoc"
_DOC_CHUNK = 45000


def load_doc() -> str:
    """KnowledgeDoc タブの分割セルを結合して資料テキストを返す。"""
    svc = _service()
    try:
        resp = (
            svc.spreadsheets()
            .values()
            .get(spreadsheetId=_cfg("KNOWLEDGE_SHEET_ID"), range=f"{_DOC_TAB}!A2:A")
            .execute()
        )
    except Exception:
        return ""
    return "".join((r[0] if r else "") for r in resp.get("values", []))


def save_doc(text: str) -> None:
    """資料テキストを KnowledgeDoc タブへ分割保存する（タブが無ければ作る）。"""
    svc = _service()
    _ensure_tab(svc, _DOC_TAB)
    sid = _cfg("KNOWLEDGE_SHEET_ID")
    svc.spreadsheets().values().clear(
        spreadsheetId=sid, range=f"{_DOC_TAB}!A:A"
    ).execute()
    text = text or ""
    chunks = [text[i : i + _DOC_CHUNK] for i in range(0, len(text), _DOC_CHUNK)] or [""]
    values = [["doc"]] + [[c] for c in chunks]
    svc.spreadsheets().values().update(
        spreadsheetId=sid,
        range=f"{_DOC_TAB}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def load() -> list[dict]:
    """シート全体を読み、知識項目の dict リストを返す。"""
    svc = _service()
    rng = f"{_tab()}!A2:C"
    resp = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=_cfg("KNOWLEDGE_SHEET_ID"), range=rng)
        .execute()
    )
    rows = resp.get("values", [])
    items: list[dict] = []
    for row in rows:
        point = (row[1] if len(row) > 1 else "").strip()
        if not point:
            continue
        item = {
            "category": (row[0] if len(row) > 0 else "").strip(),
            "point": point,
        }
        if len(row) > 2 and row[2].strip():
            item["added_at"] = row[2].strip()
        items.append(item)
    return items


def save(items: list[dict]) -> None:
    """シートを全置換で書き戻す（件数が少ないため毎回まるごと更新）。"""
    svc = _service()
    sheet_id = _cfg("KNOWLEDGE_SHEET_ID")
    _ensure_tab(svc, _tab())  # タブが無ければ作る（空のシートを渡すだけでOKにする）
    # 既存データ（ヘッダー以下）を消してから書き直す。
    svc.spreadsheets().values().clear(
        spreadsheetId=sheet_id, range=f"{_tab()}!A:C"
    ).execute()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    values = [_HEADER] + [
        [it.get("category", ""), it.get("point", ""), it.get("added_at", now)]
        for it in items
    ]
    svc.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{_tab()}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
