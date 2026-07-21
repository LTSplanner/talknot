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


# 「商談の導入」系は、信頼関係づくりを最重視して採点させる
TRUST_FOCUS = (
    "この単元の目的は『お客様と信頼関係を築き、なんでも相談してもらえる雰囲気をつくる』こと。"
    "次を最重視して採点する：\n"
    "- 警戒をほどく共感・受け止め（否定しない・今すぐ決めさせない）\n"
    "- 今日のゴール共有で安心させたか（『今日は決める場ではない』と伝えられたか）\n"
    "- 相談しやすい問いかけ（オープンな質問で、お客様が話す余白をつくれたか）\n"
    "- 売り込み感の排除（提案より先に“理解しようとする姿勢”が出ていたか）\n"
    "- 結果として、お客様が本音や不安を漏らし始める雰囲気になったか\n"
    "※ここが弱ければ、商品説明がどれだけ流暢でも高評価にしないこと。"
)
TRUST_KEYS = ["導入", "会社説明", "スケジュール"]

# お客様の属性別フォーカス（段階的にスキルアップさせる）
UNDECIDED_FOCUS = "\n".join([
    "【お客様属性：未検討】まだ必要性を感じていないお客様。ここが最難関で、最重要。",
    "- いきなり商品説明に入っていないか（説明先行は減点）",
    "- 暮らし方・家族・不満・将来の困りごとを聞き出し、本人に『言わせた』か",
    "- 引き出したニーズと商材を結び付けられたか（機能の羅列で終わっていないか）",
    "- 結果として『それなら必要かも』と本人が納得する流れを作れたか",
])
DECIDED_FOCUS = "\n".join([
    "【お客様属性：検討済み】すでに検討・見積取得済みのお客様。",
    "- 既存の検討内容を否定せず受け止めたうえで、まだ気づいていない観点を足せたか",
    "- 価格比較だけの土俵から、中身（耐久・保証・範囲）の比較へ移せたか",
    "- 見積から外されないよう、必要性を本人の言葉で再確認できたか",
])


def _customer_type(tab: str) -> tuple[str, int]:
    """タブ名から お客様属性 と 難易度レベル を決める。『未〜』は未検討版。"""
    if tab.strip().startswith("未"):
        return "未検討", 2
    return "検討済み", 1


def _sections(body: str, max_turns: int) -> list[tuple[str, str]]:
    """本文を【見出し】単位の章に分ける。戻り値 [(見出し, 本文)]。

    スプレッドシートの色付きセル＝項目見出しを【】で取り込んでいるので、
    その章立てをそのままロープレのターンに使う（読みやすく・練習しやすい）。
    """
    parts = re.split(r"\n?【([^】]+)】\n?", body)
    secs: list[tuple[str, str]] = []
    if len(parts) > 1:
        head = parts[0].strip()
        if head:
            secs.append(("導入部", head))
        for i in range(1, len(parts) - 1, 2):
            title, chunk = parts[i].strip(), parts[i + 1].strip()
            if chunk:
                secs.append((title, chunk))
    else:
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if not paras:
            return []
        size = max(1, (len(paras) + max_turns - 1) // max_turns)
        secs = [("", "\n".join(paras[i:i + size])) for i in range(0, len(paras), size)]
    return secs[:max_turns]


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

    # 取り込み済みの模範トークスクリプト（単元別・見出し付き）を情報源にする
    source = [(i.get("tab", ""), i.get("body", "")) for i in storage.get_talk_script_items()]
    if not source:
        sys.exit("模範トークスクリプトが未登録です。先に import_talk_scripts.py を実行してください。")
    # 手書きの総合シナリオを先頭に（グループ名を付ける）
    scenarios: list[dict] = []
    for s in storage._DEFAULT_SCENARIOS:
        s = dict(s)
        s["group"] = "総合商談"
        s.setdefault("customer_type", "検討済み")
        s.setdefault("level", 1)
        s.setdefault("focus", TRUST_FOCUS if s.get("id") == "first_meeting" else DECIDED_FOCUS)
        scenarios.append(s)

    seen = {s["id"] for s in scenarios}
    if True:
        for tab, body in source:
            parts = _sections(body, args.max_turns)
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
            for i, (title, chunk) in enumerate(parts):
                if i == 0:
                    customer = _opening_line(tab)
                elif title and title != "導入部":
                    customer = f"（{title}について）もう少し教えてもらえますか？"
                else:
                    customer = FOLLOW_UPS[(i - 1) % len(FOLLOW_UPS)]
                turns.append({"customer": customer, "hint": chunk, "section": title})
            ctype, level = _customer_type(tab)
            entry = {"id": sid, "group": _group_of(tab), "title": tab, "turns": turns,
                     "customer_type": ctype, "level": level}
            focus_parts = [UNDECIDED_FOCUS if ctype == "未検討" else DECIDED_FOCUS]
            if any(k in tab for k in TRUST_KEYS):
                focus_parts.append(TRUST_FOCUS)
            entry["focus"] = "\n\n".join(focus_parts)
            scenarios.append(entry)

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
