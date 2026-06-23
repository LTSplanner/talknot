"""商談議事録フォルダから実践ナレッジを増分抽出し、弊社ナレッジに展開する。

- 議事録(Googleドキュメント)を1件ずつ Gemini で要約抽出（PII除去・カテゴリ・重要度）。
- 処理済みIDは保存し、再実行では **新規分だけ** を処理（毎日の追加に随時対応）。
- 無料枠を厳守：低コストモデル＋レート throttle、429(quota)に当たったら中断して
  途中まで保存（次回・翌日に再実行で続きから）。
- 蓄積した知見を重複統合・重要度順に圧縮して meetings セクションへ展開する。

使い方:
  python3 scripts/import_meeting_minutes.py [--max 200] [--sleep 5] [--model gemini-2.5-flash-lite]
環境変数 GOOGLE_SERVICE_ACCOUNT_FILE（議事録ドライブ読取）/ KNOWLEDGE_* / GEMINI_API_KEY が必要。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from google import genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings
from services import storage

MINUTES_FOLDER_ID = "14yefycrO6ylPVT0LAqbh10HjrDV-9FDd"
SUBJECT = "ryouchiku@life-time-support.com"
DOC_MIME = "application/vnd.google-apps.document"

PROMPT = """次の住宅リフォーム商談の議事録から、今後の営業に役立つ「一般化された知識」だけを抽出してJSONで返してください。
絶対条件：個人情報（顧客氏名・担当者氏名・物件名・住所・電話番号・メール・商談ID・その案件固有の金額）は一切含めない。必ず一般化して書く。
カテゴリ: product(商品知識) / rule(社内ルール・運用) / technique(トーク技術) / customer(お客様の不安・反応パターン)。
各項目に importance(1-5, 5=最重要) を付ける。学びが薄いもの・一般論すぎるものは出さない。
出力はJSONのみ: {"items":[{"category":"...","insight":"...","importance":3}]}"""


def _drive():
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=settings.DRIVE_SCOPES, subject=SUBJECT
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_docs(drv) -> list[dict]:
    out, tok = [], None
    while True:
        r = drv.files().list(
            q=f"'{MINUTES_FOLDER_ID}' in parents and trashed=false and mimeType='{DOC_MIME}'",
            fields="nextPageToken, files(id,name)",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            pageSize=500, pageToken=tok,
        ).execute()
        out += r.get("files", [])
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


class QuotaHit(Exception):
    """無料枠の上限（429）に到達。中断して途中保存する。"""


def _extract(gc, model: str, text: str, tries: int = 4) -> list[dict]:
    for i in range(tries):
        try:
            resp = gc.models.generate_content(
                model=model,
                contents=PROMPT + "\n\n---議事録---\n" + text[:16000],  # 要点(概要/次の一歩/序盤詳細)で十分
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text).get("items", [])
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                raise QuotaHit(msg)
            if "503" in msg and i < tries - 1:
                time.sleep(5)
                continue
            if i < tries - 1:
                time.sleep(2)
                continue
            return []
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=600, help="今回処理する最大件数")
    ap.add_argument("--sleep", type=float, default=0.0, help="各抽出の間隔秒（必要なら）")
    ap.add_argument("--flush", type=int, default=20, help="シート保存の間隔（件）")
    ap.add_argument("--model", default="gemini-2.5-flash-lite", help="抽出モデル（無料枠の広いもの推奨）")
    args = ap.parse_args()

    if not settings.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY が未設定です。")
    drv = _drive()
    gc = genai.Client(api_key=settings.GEMINI_API_KEY)

    docs = _list_docs(drv)
    rows = storage._load_meeting_insights()  # 既存（処理済み）を起点に積み増す
    done = {r.get("doc_id") for r in rows if r.get("doc_id")}
    todo = [d for d in docs if d["id"] not in done][: args.max]
    print(f"議事録 総数 {len(docs)} ／ 処理済み {len(done)} ／ 今回処理 {len(todo)} 件（{args.model}）",
          flush=True)

    now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
    processed = added_total = 0

    def flush():
        storage._save_meeting_insights(rows)

    try:
        for i, d in enumerate(todo, 1):
            try:
                text = drv.files().export(fileId=d["id"], mimeType="text/plain").execute()
                text = text.decode("utf-8", "ignore") if isinstance(text, (bytes, bytearray)) else str(text)
                items = _extract(gc, args.model, text)
            except QuotaHit:
                raise
            except Exception as e:  # noqa: BLE001
                print(f"  skip {d['name'][:30]}: {str(e)[:80]}", flush=True)
                items = []
            n = 0
            for it in items:
                ins = (it.get("insight") or "").strip()
                if not ins:
                    continue
                rows.append({"doc_id": d["id"], "category": (it.get("category") or "").strip(),
                             "insight": ins, "importance": str(it.get("importance", "")), "added_at": now()})
                n += 1
            if n == 0:  # 知見ゼロでも処理済みマーカー
                rows.append({"doc_id": d["id"], "category": "", "insight": "", "importance": "", "added_at": now()})
            processed += 1
            added_total += n
            if i % args.flush == 0:
                flush()
                print(f"  {i}/{len(todo)} 処理・保存（累計知見 {added_total}）", flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    except QuotaHit as q:
        print(f"⚠️ 無料枠の上限に到達（429）。{processed}件で中断し途中保存します。"
              f"翌日/ボタンで再実行すると続きから。\n  {str(q)[:140]}", flush=True)

    flush()
    print(f"処理 {processed} 件 / 抽出知見 {added_total} 件", flush=True)
    n = storage.distill_meeting_knowledge()
    rest = len([d for d in docs if d["id"] not in {r.get("doc_id") for r in rows if r.get("doc_id")}])
    print(f"💾 重要度順に {n} 件を meetings セクションへ展開。未処理の残り 約 {rest} 件", flush=True)


if __name__ == "__main__":
    main()
