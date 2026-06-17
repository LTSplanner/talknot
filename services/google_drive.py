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


def list_videos(credentials: Credentials, name_contains: str | None = None) -> list[dict]:
    """アクセス可能な動画を新しい順で返す（共有ドライブ・共有アイテム含む）。

    name_contains を指定するとファイル名で絞り込む（例: "商談", "Meet"）。
    各要素: {id, name, createdTime, size, owner, webViewLink}
    """
    service = _service(credentials)
    query = _VIDEO_QUERY
    if name_contains:
        safe = name_contains.replace("'", "\\'")
        query += f" and name contains '{safe}'"

    files: list[dict] = []
    page_token = None
    # corpora='allDrives' では orderBy が使えないため取得後に Python 側で並べ替える。
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                corpora="allDrives",
                includeItemsFromAllDrives=True,
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


def download_file(credentials: Credentials, file_id: str) -> bytes:
    """指定 file_id の動画をメモリ上に取得して bytes で返す。"""
    service = _service(credentials)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()
