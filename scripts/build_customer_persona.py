"""議事録から抽出済みの『お客様知見』を集約し、リアルなお客様ペルソナを作る。

- 情報源：storage の蓄積済み meeting insights（category=customer を中心に活用）。
  ＝すでに議事録を分析した結果を使うので、追加のGemini呼び出しは1回だけ（無料枠内）。
- 出力：属性別（検討済み／未検討）に「よくある反応・不安・口ぐせ・断り文句」をまとめた
  ペルソナ辞書を storage に保存。ロープレの台本（カンペ）に自然な“お客様の声”を混ぜる。

使い方:  python3 scripts/build_customer_persona.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys

from google import genai

from config import settings
from services import storage

PROMPT = """あなたは住宅リフォーム営業のトレーナーです。以下は実際の商談から抽出した
「お客様の反応・傾向」の知見リストです。これを素材に、ロープレ練習で使う“リアルなお客様像”を
JSONで作ってください。

必ず日本語。個人情報（氏名・物件名・金額の固有値）は入れない。実際の商談で頻出する
自然な言い回しにする。属性は2つ：
- decided（すでに検討・見積取得済みで来たお客様）
- undecided（特に検討しておらず、必要性を感じていないお客様）

各属性について次を作る：
- opening: そのお客様が商談の最初に言いそうな第一声（3〜5個、口語で自然に）
- concerns: 抱えがちな本音・不安（4〜6個、短文）
- objections: 断り・保留のときの言い回し（4〜6個、口語。例「主人と相談して…」）
- verbal_tics: 口ぐせ・相槌（3〜5個。例「うーん」「なるほど」「そうですね…」）

出力JSONのみ:
{"decided":{"opening":[],"concerns":[],"objections":[],"verbal_tics":[]},
 "undecided":{"opening":[],"concerns":[],"objections":[],"verbal_tics":[]}}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not settings.GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY が未設定です。")

    insights = storage._load_meeting_insights()
    # お客様反応（customer）を主に、トーク技術(technique)も少し混ぜて材料にする
    material = [i["insight"] for i in insights
               if i.get("insight") and i.get("category") in ("customer", "technique")]
    if not material:
        sys.exit("お客様知見がありません。先に議事録を取り込んでください。")
    material = material[:220]
    print(f"素材となるお客様知見：{len(material)} 件")

    gc = genai.Client(api_key=settings.GEMINI_API_KEY)
    resp = gc.models.generate_content(
        model=settings.MINUTES_EXTRACT_MODEL,
        contents=PROMPT + "\n\n---知見リスト---\n" + "\n".join(f"- {m}" for m in material),
        config={"response_mime_type": "application/json"},
    )
    persona = json.loads(resp.text)

    for key in ("decided", "undecided"):
        p = persona.get(key, {})
        print(f"\n■ {key}: opening {len(p.get('opening',[]))} / concerns {len(p.get('concerns',[]))}"
              f" / objections {len(p.get('objections',[]))} / tics {len(p.get('verbal_tics',[]))}")
        for o in p.get("opening", [])[:2]:
            print("   例(第一声):", o)

    if args.dry_run:
        print("\n--dry-run のため保存しません。")
        return
    storage.set_customer_persona(persona)
    print("\n💾 ペルソナを保存しました。ロープレ台本に反映されます。")


if __name__ == "__main__":
    main()
