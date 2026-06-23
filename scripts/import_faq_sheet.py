"""FAQ統合シートから、商品・料金・サービスのQ&Aを厳選して弊社ナレッジに追加する。

- 入力: 整備済みFAQシート（category,question,answer,cluster_size,confidence,...）。
- 重複排除（質問の正規化＋回答シグネチャ）、頻度(cluster_size)・信頼度(confidence)で厳選。
- 個人情報（メール・電話・URL）はスクラブし、含む行は捨てる（PII厳守）。
- カテゴリごとに頻度上位を、文字数バジェット内で採用。
- 既存の社内資料ドキュメント（整備版5資料）に「FAQ」セクションとして“追記”する
  （再実行しても二重化しないよう、既存FAQブロックは置き換える）。

使い方:  python3 scripts/import_faq_sheet.py [--budget 40000] [--dry-run]
保存先は storage（KNOWLEDGE_SHEET_ID 設定時は共有シートの KnowledgeDoc タブ）。
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import defaultdict

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings
from services import storage

FAQ_SHEET_ID = "1SmK5lFPjYIMwjlRF-ERS9kJay-yYDq_mfMDMiWXvUj0"
SUBJECT = "ryouchiku@life-time-support.com"
MARKER = "===== FAQ（よくある質問・自動抽出 / 個人情報は除外） ====="
PER_CAT_CAP = 60  # 1カテゴリあたりの最大採用数

# 個人情報らしきパターン（含む行は丸ごと除外）
_PII = re.compile(
    r"(\S+@\S+\.\S+)"                       # メール
    r"|(https?://\S+)"                      # URL
    r"|(0\d{1,3}[-(]?\d{2,4}[-)]?\d{3,4})"  # 電話
    r"|(\d{3}-?\d{4}\b)"                    # 郵便番号っぽい
)


def _csv_from_sheet() -> str:
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_FILE が未設定です。")
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=settings.DRIVE_SCOPES, subject=SUBJECT
    )
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    data = svc.files().export(fileId=FAQ_SHEET_ID, mimeType="text/csv").execute()
    return data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data)


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", (t or "")).lower()


def build_faq_block(csv_text: str, budget: int) -> tuple[str, dict]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    # 1) 重複排除：質問の正規化キーで cluster_size 最大のものを残す
    best: dict[str, dict] = {}
    for r in rows:
        if int(r.get("confidence", 0) or 0) < 80:
            continue
        q = (r.get("question") or "").strip()
        a = (r.get("answer") or "").strip()
        if not q or not a:
            continue
        if _PII.search(q) or _PII.search(a):  # 個人情報は丸ごと除外
            continue
        k = _norm(q)
        cs = int(r.get("cluster_size", 0) or 0)
        if k not in best or cs > int(best[k].get("cluster_size", 0) or 0):
            best[k] = r

    # 2) 回答シグネチャでも近重複を排除（言い換えダブり対策）
    by_cat: dict[str, list[dict]] = defaultdict(list)
    sig_seen: set[str] = set()
    for r in sorted(best.values(), key=lambda x: -int(x.get("cluster_size", 0) or 0)):
        cat = (r.get("category") or "その他").strip()
        sig = cat + "|" + _norm(r.get("answer", ""))[:40]
        if sig in sig_seen:
            continue
        sig_seen.add(sig)
        by_cat[cat].append(r)

    # 3) カテゴリごとに頻度上位を、全体バジェット内で採用
    picked: dict[str, list[dict]] = defaultdict(list)
    total = 0
    # カテゴリを大きい順に回し、各カテゴリ上位から1問ずつ詰める（広く・濃く）
    cat_order = sorted(by_cat, key=lambda c: -len(by_cat[c]))
    idx = 0
    while total < budget:
        progressed = False
        for cat in cat_order:
            lst = by_cat[cat]
            if idx < len(lst) and len(picked[cat]) < PER_CAT_CAP:
                r = lst[idx]
                line = len(r["question"]) + len(r["answer"]) + 8
                if total + line > budget:
                    continue
                picked[cat].append(r)
                total += line
                progressed = True
        if not progressed:
            break
        idx += 1

    # 4) 整形
    parts = [MARKER]
    counts = {}
    for cat in cat_order:
        items = picked[cat]
        if not items:
            continue
        counts[cat] = len(items)
        parts.append(f"\n■ {cat}")
        for r in items:
            parts.append(f"Q. {r['question'].strip()}\nA. {r['answer'].strip()}")
    return "\n".join(parts), counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=40000, help="FAQ枠の最大文字数")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    csv_text = _csv_from_sheet()
    faq_block, counts = build_faq_block(csv_text, args.budget)

    print("採用したFAQ（カテゴリ別 件数）:")
    for c, n in counts.items():
        print(f"  {n:4d}  {c}")
    print(f"FAQブロック文字数: {len(faq_block)}")

    print(f"FAQセクション文字数: {len(faq_block)}")

    if args.dry_run:
        print("--dry-run のため保存しません。\n--- FAQ先頭800字 ---")
        print(faq_block[:800])
        return

    # FAQ は独立セクション（faq）として保存。整備版(base)・議事録(meetings)には干渉しない。
    storage.set_knowledge_doc(faq_block, kind="faq")
    where = "共有シートの KnowledgeFAQ タブ" if storage._use_sheets() else "ローカル/GCS"
    print(f"💾 保存しました → {where}")


if __name__ == "__main__":
    main()
