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


def configured() -> bool:
    """スプレッドシート保存が使える設定がそろっているか。"""
    return bool(settings.KNOWLEDGE_SHEET_ID) and bool(
        settings.KNOWLEDGE_SA_JSON or settings.KNOWLEDGE_SA_FILE
    )


def _service():
    """Sheets API クライアントを返す（依存は遅延 import）。"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if settings.KNOWLEDGE_SA_JSON:
        info = json.loads(settings.KNOWLEDGE_SA_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=settings.SHEETS_SCOPES
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            settings.KNOWLEDGE_SA_FILE, scopes=settings.SHEETS_SCOPES
        )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _tab() -> str:
    return settings.KNOWLEDGE_SHEET_TAB


def load() -> list[dict]:
    """シート全体を読み、知識項目の dict リストを返す。"""
    svc = _service()
    rng = f"{_tab()}!A2:C"
    resp = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=settings.KNOWLEDGE_SHEET_ID, range=rng)
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
    sheet_id = settings.KNOWLEDGE_SHEET_ID
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
