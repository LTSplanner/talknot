"""サービスアカウント＋ドメイン全体委任（DWD）による代理ドライブアクセス。

各メンバー（settings.TARGET_ACCOUNTS）になりすまして（impersonate）、その人の
ドライブ上の録画にアクセスする。各メンバーのログインは不要。

前提（Workspace 超管理者の設定が必要）:
  1. GCP でサービスアカウントを作成し JSON 鍵を発行 → GOOGLE_SERVICE_ACCOUNT_FILE
  2. Admin Console でそのサービスアカウントのクライアントIDに
     settings.DRIVE_SCOPES（drive.readonly）をドメイン全体委任で許可
  詳細は docs/SETUP_SERVICE_ACCOUNT.md。

取得・ダウンロード自体は services.google_drive の関数を再利用する
（impersonate した Credentials を渡すだけ）。
"""
from __future__ import annotations

from pathlib import Path

from google.oauth2 import service_account

from config import settings


def configured() -> bool:
    """サービスアカウント鍵が設定され、ファイルが存在するか。"""
    path = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    return bool(path) and Path(path).expanduser().exists()


def impersonate(subject_email: str) -> service_account.Credentials:
    """指定メンバーになりすました Drive 用 Credentials を返す。

    services.google_drive.list_videos / download_file にそのまま渡せる。
    """
    if not configured():
        raise RuntimeError(
            "サービスアカウント鍵が未設定です（GOOGLE_SERVICE_ACCOUNT_FILE）。"
        )
    return service_account.Credentials.from_service_account_file(
        str(Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE).expanduser()),
        scopes=settings.DRIVE_SCOPES,
        subject=subject_email,
    )
