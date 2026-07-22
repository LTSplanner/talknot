"""施工事例ギャラリー（フックツール）：写真の保存・一覧・取得。

- 写真は共有 Drive フォルダ（settings.GALLERY_FOLDER_ID）に保存する。
  Streamlit Cloud はディスクが揮発するため、永続化に Drive を使う。
- 書き込みは最小権限の知識SAで行う（フォルダを知識SAに「編集者」で共有しておく）。
- アップロードは管理者のみ・閲覧/ダウンロードは全ユーザー、という制御はUI側で行う。
- カテゴリ・キャプションは Drive の appProperties / description に保存する。
"""
from __future__ import annotations

import io
import json

from config import settings

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_IMG_QUERY = "mimeType contains 'image/' and trashed = false"


def _drive():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_json = getattr(settings, "KNOWLEDGE_SA_JSON", "") or ""
    sa_file = getattr(settings, "KNOWLEDGE_SA_FILE", "") or ""
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=_SCOPES
        )
    elif sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=_SCOPES)
    else:
        raise RuntimeError("知識SA（KNOWLEDGE_SA_*）が未設定です。")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def configured() -> bool:
    has_sa = bool(getattr(settings, "KNOWLEDGE_SA_JSON", "") or getattr(settings, "KNOWLEDGE_SA_FILE", ""))
    return bool(has_sa and settings.GALLERY_FOLDER_ID)


def list_photos(category: str | None = None) -> list[dict]:
    """フォルダ内の写真を新しい順で返す。各要素: {id, name, category, caption, created}"""
    svc = _drive()
    q = f"'{settings.GALLERY_FOLDER_ID}' in parents and {_IMG_QUERY}"
    items, tok = [], None
    while True:
        resp = svc.files().list(
            q=q, orderBy="createdTime desc",
            fields="nextPageToken, files(id,name,createdTime,description,appProperties)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageSize=200, pageToken=tok,
        ).execute()
        items += resp.get("files", [])
        tok = resp.get("nextPageToken")
        if not tok:
            break
    out = []
    for f in items:
        props = f.get("appProperties") or {}
        cat = props.get("category", "その他")
        if category and category != "すべて" and cat != category:
            continue
        out.append({
            "id": f["id"], "name": f.get("name", ""), "category": cat,
            "caption": f.get("description", "") or props.get("caption", ""),
            "created": f.get("createdTime", "")[:10],
        })
    return out


def upload_photo(data: bytes, filename: str, category: str, caption: str, mime: str) -> str:
    """写真を1枚アップロードする（管理者操作）。file_id を返す。"""
    from googleapiclient.http import MediaIoBaseUpload

    svc = _drive()
    meta = {
        "name": filename,
        "parents": [settings.GALLERY_FOLDER_ID],
        "description": caption or "",
        "appProperties": {"category": category or "その他"},
    }
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime or "image/jpeg", resumable=False)
    f = svc.files().create(
        body=meta, media_body=media, fields="id", supportsAllDrives=True
    ).execute()
    return f["id"]


def photo_bytes(file_id: str) -> bytes:
    """写真の実体を取得する（表示・ダウンロード用）。"""
    from googleapiclient.http import MediaIoBaseDownload

    svc = _drive()
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def delete_photo(file_id: str) -> None:
    """写真を削除する（管理者操作）。"""
    _drive().files().delete(fileId=file_id, supportsAllDrives=True).execute()
