"""Google ドライブの『整備済みナレッジ資料』フォルダを TalKnot のナレッジへ取り込む。

社内の質疑応答AI用に作成済みの商品・料金・サービス・FAQ ドキュメントを読み込み、
評価プロンプトの「弊社ナレッジ」に毎回差し込む社内資料として保存する。

- 取り込み対象: フォルダ直下の Google ドキュメント＋小さいスプレッドシート。
  巨大な FAQ 統合シート・生 CSV・メール書庫サブフォルダは取り込まない。
- 読み込みには録画用の DWD サービスアカウント（GOOGLE_SERVICE_ACCOUNT_FILE）を使い、
  フォルダ所有者を代理（--subject）してエクスポートする。
- 保存先は storage（KNOWLEDGE_SHEET_ID 設定済みなら共有ドライブのシートへ永続保存）。

使い方:
    python3 scripts/import_knowledge_folder.py <folder_id> [--subject owner@domain]
"""
from __future__ import annotations

import argparse
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings
from services import google_drive, storage

DEFAULT_FOLDER = "15Q4Ei08Xubfib_0T2HcwYpdk93BDudl8"
DEFAULT_SUBJECT = "ryouchiku@life-time-support.com"


def _drive_service(subject: str):
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_FILE が未設定です（.env を確認）。")
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=settings.DRIVE_SCOPES,
        subject=subject,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder_id", nargs="?", default=DEFAULT_FOLDER)
    ap.add_argument("--subject", default=DEFAULT_SUBJECT, help="フォルダ所有者（代理アクセス）")
    ap.add_argument("--dry-run", action="store_true", help="保存せず内容だけ確認")
    args = ap.parse_args()

    svc = _drive_service(args.subject)
    text, included, skipped = google_drive.export_knowledge_folder(svc, args.folder_id)

    print(f"取り込み対象 {len(included)} 件 / 除外 {len(skipped)} 件")
    for n in included:
        print(f"  ✅ {n}")
    for n in skipped:
        print(f"  ⏭️  {n}")
    print(f"合計 {len(text)} 文字（≈ {len(text)//3} tokens 目安）")

    if not text:
        sys.exit("取り込めるテキストがありませんでした。")
    if args.dry_run:
        print("--dry-run のため保存しません。")
        return

    storage.set_knowledge_doc(text)
    where = (
        "共有ドライブのスプレッドシート（KnowledgeDoc タブ）"
        if storage._use_sheets()
        else "ローカル/GCS"
    )
    print(f"💾 保存しました → {where}")


if __name__ == "__main__":
    main()
