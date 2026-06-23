"""Google ドライブ連携：アクセス可能な動画の一覧取得とダウンロード。

auth.session が保持する Credentials を受け取り Drive v3 を呼び出す。
マイドライブ・共有ドライブ・自分に共有されたファイルを横断して検索する
（corpora='allDrives'）。

注意: Google の権限モデル上、ログイン中ユーザーが「所有」または「共有されて
いる」動画のみが見える。他メンバーの個人ドライブにある録画は、共有されるか
共有ドライブに置かれない限り表示されない。
"""
from __future__ import annotations

import io

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

_VIDEO_QUERY = "mimeType contains 'video/' and trashed = false"


def _service(credentials: Credentials):
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def list_videos(
    credentials: Credentials,
    name_contains: str | None = None,
    owned_only: bool = False,
) -> list[dict]:
    """アクセス可能な動画を新しい順で返す。

    name_contains を指定するとファイル名で絞り込む（例: "商談", "Meet"）。
    owned_only=True のときは、**ログイン中ユーザー自身が所有する動画のみ**を返す
    （共有された他人の動画・共有ドライブの動画は除外。プライバシー厳守用）。
    各要素: {id, name, createdTime, size, owner, webViewLink}
    """
    service = _service(credentials)
    query = _VIDEO_QUERY
    if name_contains:
        safe = name_contains.replace("'", "\\'")
        query += f" and name contains '{safe}'"
    if owned_only:
        # 認証ユーザー本人が所有するファイルだけ（= 自分のアドレスに紐づく動画）。
        query += " and 'me' in owners"

    # 自分所有のみのときはマイドライブ範囲（共有ドライブ・共有アイテムを含めない）。
    corpora = "user" if owned_only else "allDrives"
    include_all = not owned_only

    files: list[dict] = []
    page_token = None
    # corpora='allDrives' では orderBy が使えないため取得後に Python 側で並べ替える。
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                corpora=corpora,
                includeItemsFromAllDrives=include_all,
                supportsAllDrives=True,
                fields=(
                    "nextPageToken, "
                    "files(id, name, createdTime, size, webViewLink, owners(emailAddress))"
                ),
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    for f in files:
        owners = f.get("owners") or []
        f["owner"] = owners[0]["emailAddress"] if owners else ""
    files.sort(key=lambda f: f.get("createdTime", ""), reverse=True)
    return files


# 後方互換: Meet 録画フォルダ名でのざっくり絞り込み
def list_meet_recordings(credentials: Credentials, folder_name: str = "Meet") -> list[dict]:
    """Meet 録画を想定した一覧。まず名前に folder_name を含む動画を探し、

    無ければアクセス可能な全動画を返す。
    """
    videos = list_videos(credentials, name_contains=folder_name)
    if videos:
        return videos
    return list_videos(credentials)


# 整備済みナレッジ資料として取り込む対象の判定。
# Google ドキュメントは常に対象。スプレッドシートは「小さいもの」だけ対象にし、
# 巨大な FAQ 統合シート・生 CSV・メール書庫サブフォルダは取り込まない。
_DOC_MIME = "application/vnd.google-apps.document"
_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_SHEET_TEXT_LIMIT = 50000


def _export_text(service, file_id: str, mime: str) -> str:
    data = service.files().export(fileId=file_id, mimeType=mime).execute()
    return data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data)


def export_knowledge_folder(service, folder_id: str) -> tuple[str, list[str], list[str]]:
    """フォルダ直下の整備済み資料（Docs＋小さい Sheets）をテキスト化して結合する。

    再帰しない（メール書庫サブフォルダを巻き込まないため）。
    戻り値: (結合テキスト, 取り込んだ名前リスト, 除外した名前リスト)
    """
    resp = (
        service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, mimeType)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=500,
        )
        .execute()
    )
    files = sorted(resp.get("files", []), key=lambda f: f.get("name", ""))
    parts: list[str] = []
    included: list[str] = []
    skipped: list[str] = []
    for f in files:
        name, mime = f.get("name", ""), f.get("mimeType", "")
        if mime == _DOC_MIME:
            txt = _export_text(service, f["id"], "text/plain")
        elif mime == _SHEET_MIME:
            txt = _export_text(service, f["id"], "text/csv")
            if len(txt) > _SHEET_TEXT_LIMIT:
                skipped.append(f"{name}（大きすぎるため除外 {len(txt)}字）")
                continue
        else:
            skipped.append(f"{name}（対象外）")
            continue
        txt = (txt or "").strip()
        if not txt:
            skipped.append(f"{name}（空）")
            continue
        parts.append(f"# {name}\n{txt}")
        included.append(name)
    return "\n\n".join(parts), included, skipped


def download_file(credentials: Credentials, file_id: str) -> bytes:
    """指定 file_id の動画をメモリ上に取得して bytes で返す（小さいファイル向け）。"""
    service = _service(credentials)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def download_to_path(
    credentials: Credentials, file_id: str, dest_path: str, chunk_mb: int = 16
) -> None:
    """指定 file_id をファイルへ逐次（チャンク）保存する。

    メモリに全体を載せないため、2〜3時間の大容量録画でも省メモリで取得できる。
    """
    service = _service(credentials)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_mb * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
