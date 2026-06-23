"""商談議事録から実践ナレッジを抽出する共通ロジック（アプリ内ボタン用）。

- クラウドでは最小権限の知識SA（KNOWLEDGE_SA_*）で議事録フォルダを読む。
  そのため議事録フォルダを知識SAに「閲覧者」で共有しておくこと。
- 抽出は無料枠の広いモデル（settings.MINUTES_EXTRACT_MODEL）。PIIは必ず除外。
- 1回の実行は limit 件までの「新規分」だけ処理（増分・再開可能）。
"""
from __future__ import annotations

import json
import time

from config import settings
from services import storage

PROMPT = """次の住宅リフォーム商談の議事録から、今後の営業に役立つ「一般化された知識」だけを抽出してJSONで返してください。
絶対条件：個人情報（顧客氏名・担当者氏名・物件名・住所・電話番号・メール・商談ID・その案件固有の金額）は一切含めない。必ず一般化して書く。
カテゴリ: product(商品知識) / rule(社内ルール・運用) / technique(トーク技術) / customer(お客様の不安・反応パターン)。
各項目に importance(1-5, 5=最重要) を付ける。学びが薄いもの・一般論すぎるものは出さない。
出力はJSONのみ: {"items":[{"category":"...","insight":"...","importance":3}]}"""

DOC_MIME = "application/vnd.google-apps.document"


def _gemini():
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _sa_drive():
    """知識SAで Drive を読むクライアント（議事録フォルダが共有されている前提）。"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    sa_json = getattr(settings, "KNOWLEDGE_SA_JSON", "")
    sa_file = getattr(settings, "KNOWLEDGE_SA_FILE", "")
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=scopes
        )
    elif sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)
    else:
        raise RuntimeError("知識SA（KNOWLEDGE_SA_*）が未設定です。")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def configured() -> bool:
    """ボタンから議事録取り込みが使える設定がそろっているか。"""
    has_sa = bool(getattr(settings, "KNOWLEDGE_SA_JSON", "") or getattr(settings, "KNOWLEDGE_SA_FILE", ""))
    return bool(settings.GEMINI_API_KEY and has_sa and settings.MINUTES_FOLDER_ID)


def _list_docs(drive) -> list[dict]:
    out, tok = [], None
    while True:
        r = drive.files().list(
            q=f"'{settings.MINUTES_FOLDER_ID}' in parents and trashed=false and mimeType='{DOC_MIME}'",
            fields="nextPageToken, files(id,name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageSize=500, pageToken=tok,
        ).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def _extract(gc, model: str, text: str, tries: int = 3) -> list[dict]:
    for i in range(tries):
        try:
            resp = gc.models.generate_content(
                model=model,
                contents=PROMPT + "\n\n---議事録---\n" + text[:16000],
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text).get("items", [])
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise
            if i < tries - 1:
                time.sleep(4 if "503" in msg else 2)
                continue
            return []
    return []


def remaining_count(drive=None) -> tuple[int, int]:
    """(未処理件数, 総件数) を返す。"""
    drive = drive or _sa_drive()
    docs = _list_docs(drive)
    done = storage.get_processed_meeting_ids()
    return len([d for d in docs if d["id"] not in done]), len(docs)


def run_extraction(limit: int = 30, drive=None) -> dict:
    """新規議事録を最大 limit 件処理して保存・蒸留する。結果サマリ dict を返す。"""
    drive = drive or _sa_drive()
    gc = _gemini()
    model = settings.MINUTES_EXTRACT_MODEL
    docs = _list_docs(drive)
    rows = storage._load_meeting_insights()
    done = {r.get("doc_id") for r in rows if r.get("doc_id")}
    todo = [d for d in docs if d["id"] not in done][:limit]

    processed = added = 0
    quota = False
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for d in todo:
        try:
            text = drive.files().export(fileId=d["id"], mimeType="text/plain").execute()
            text = text.decode("utf-8", "ignore") if isinstance(text, (bytes, bytearray)) else str(text)
            items = _extract(gc, model, text)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                quota = True
                break
            items = []
        n = 0
        for it in items:
            ins = (it.get("insight") or "").strip()
            if not ins:
                continue
            rows.append({"doc_id": d["id"], "category": (it.get("category") or "").strip(),
                         "insight": ins, "importance": str(it.get("importance", "")), "added_at": now})
            n += 1
        if n == 0:
            rows.append({"doc_id": d["id"], "category": "", "insight": "", "importance": "", "added_at": now})
        processed += 1
        added += n

    storage._save_meeting_insights(rows)
    distilled = storage.distill_meeting_knowledge()
    done2 = {r.get("doc_id") for r in rows if r.get("doc_id")}
    remaining = len([d for d in docs if d["id"] not in done2])
    return {"processed": processed, "added": added, "distilled": distilled,
            "remaining": remaining, "total": len(docs), "quota": quota}
