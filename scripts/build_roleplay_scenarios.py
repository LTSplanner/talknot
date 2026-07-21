"""模範トークスクリプトの各タブから、1人ロープレの「商材・単元別シナリオ」を作る。

- スクリプト1タブ ＝ ロープレ1単元（例：ガラス説明／セラミック説明／エコカラットの価格…）。
- 各ターンの「カンペ」は **実際のスクリプト本文** をそのまま使う（AI不使用＝無料）。
- お客様のセリフは、タブ名と定型の掘り下げ質問から機械的に組み立てる。
- 手書きの総合シナリオ（初回商談／反論対応／クロージング）は先頭に残す。

使い方:
    python3 scripts/build_roleplay_scenarios.py [--dry-run] [--max-turns 4]
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import service_account

from config import settings
from services import storage

SCRIPT_BOOKS = [
    "1bUrsQxKIg7DZc-DANvHRqR4ygeEQEOvckZTpeGlmyEs",
    "1A92RANfvc9zQz18b9aG4fnSlurKAqBVr0iWAzGSAX1k",
]
SUBJECT = "planner@life-time-support.com"

# タブ名からカテゴリ（プルダウンの大分類）を決める
GROUPS = [
    ("コーティング", ["コーティング", "ガラス説明", "UV説明", "シリコン説明", "セラミック説明", "整い版"]),
    ("エコカラット", ["エコカラット", "エコLD"]),
    ("エアコン", ["エアコン"]),
    ("収納・家具", ["食器棚", "吊戸棚", "可変棚", "小物", "ピクチャーレール", "マジキャビ"]),
    ("住設・その他商材", ["住設", "食洗機", "窓フィルム", "ミラーフィルム", "カーテン"]),
    ("商談の流れ", ["導入", "会社説明", "内覧会", "締め", "スケジュール", "引っ越し"]),
]

FOLLOW_UPS = [
    "なるほど。もう少し詳しく教えてもらえますか？",
    "それだと、どんなメリットがあるんでしょうか。",
    "他の選択肢と比べると、どう違いますか？",
    "費用面や期間はどうなりますか？",
]


def _group_of(tab: str) -> str:
    for name, keys in GROUPS:
        if any(k in tab for k in keys):
            return name
    return "その他"


def _opening_line(tab: str) -> str:
    t = tab.strip()
    if t.endswith("？") or t.endswith("?"):
        return t
    t = re.sub(r"^(未|必ず話す)\s*", "", t)
    return f"{t}について、まだよく分かっていなくて。教えてもらえますか？"


def _chunks(body: str, max_turns: int) -> list[str]:
    """スクリプト本文を、ターン数ぶんの塊に分ける（段落単位でまとめる）。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[■●◆])", body) if p.strip()]
    if not paras:
        return []
    if len(paras) <= max_turns:
        return paras
    # 段落数が多いときは、ほぼ均等になるよう束ねる
    size = (len(paras) + max_turns - 1) // max_turns
    return ["\n".join(paras[i:i + size]) for i in range(0, len(paras), size)][:max_turns]


def _token() -> str:
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_FILE が未設定です。")
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        subject=SUBJECT,
    )
    creds.refresh(Request())
    return creds.token


def _tabs(sheet_id: str, token: str) -> list[tuple[str, str]]:
    import openpyxl

    req = urllib.request.Request(
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx",
        headers={"Authorization": f"Bearer {token}"},
    )
    wb = openpyxl.load_workbook(io.BytesIO(urllib.request.urlopen(req, timeout=120).read()),
                                data_only=True)
    out = []
    for name in wb.sheetnames:
        cells = []
        for row in wb[name].iter_rows(values_only=True):
            for c in row:
                if c and str(c).strip():
                    cells.append(str(c).strip())
        body = "\n".join(cells).strip()
        if body:
            out.append((name, body))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-turns", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = _token()
    # 手書きの総合シナリオを先頭に（グループ名を付ける）
    scenarios: list[dict] = []
    for s in storage._DEFAULT_SCENARIOS:
        s = dict(s)
        s["group"] = "総合商談"
        scenarios.append(s)

    seen = {s["id"] for s in scenarios}
    for sheet_id in SCRIPT_BOOKS:
        for tab, body in _tabs(sheet_id, token):
            parts = _chunks(body, args.max_turns)
            if not parts:
                continue
            sid = re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-龥]+", "_", tab).strip("_")[:40] or f"t{len(seen)}"
            base = sid
            n = 2
            while sid in seen:
                sid = f"{base}_{n}"
                n += 1
            seen.add(sid)
            turns = []
            for i, chunk in enumerate(parts):
                customer = _opening_line(tab) if i == 0 else FOLLOW_UPS[(i - 1) % len(FOLLOW_UPS)]
                turns.append({"customer": customer, "hint": chunk})
            scenarios.append({
                "id": sid, "group": _group_of(tab), "title": tab, "turns": turns,
            })

    by_group: dict[str, int] = {}
    for s in scenarios:
        by_group[s.get("group", "その他")] = by_group.get(s.get("group", "その他"), 0) + 1
    print(f"生成シナリオ: {len(scenarios)} 単元")
    for g, n in by_group.items():
        print(f"  ■ {g}: {n} 単元")

    if args.dry_run:
        print("--dry-run のため保存しません。")
        for s in scenarios[3:6]:
            print(f"\n--- {s['group']} / {s['title']} ---")
            for t in s["turns"][:2]:
                print("  🧑", t["customer"])
                print("  📋", t["hint"][:100].replace("\n", " "), "…")
        return

    storage.set_scenarios(scenarios)
    print(f"💾 保存しました（読み戻し {len(storage.get_scenarios())} 単元）")


if __name__ == "__main__":
    main()
