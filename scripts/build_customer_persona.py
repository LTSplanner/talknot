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

PROMPT = """あなたは新築マンションのリフォーム/オプション営業のトレーナーです。
以下は実際の商談から抽出した「お客様の反応・傾向」の知見リストです。これを素材に、
ロープレ練習で使う“リアルなお客様像”をJSONで作ってください。

【弊社の商談の前提（厳守）】
- 商談は全て「内覧会の前」（新築マンションの入居前）に行う。最終決定は内覧会の採寸後。
  → 「内覧会に行ったんですけど」「住んでみて」など、内覧会後・入居後を前提にした
    セリフは誤りなので絶対に作らない。
- 未検討のお客様は自分から要望を言わない“受け身”タイプ。第一声は曖昧で消極的にする。
  営業が話のタネを撒いてはじめて少し反応する。「全部お願いしたい」のような積極的な入りはしない。
  「ネットで見た商品扱ってますか？」のような、ざっくりした質問一つで商談が始まる入りもしない。
- 検討済みのお客様は、既に具体的な検討商材や見積がある。第一声も具体的にする。

必ず日本語。個人情報（氏名・物件名・金額の固有値）は入れない。属性は2つ：
- decided（既に具体的に検討・見積取得済みで来たお客様）
- undecided（特に検討しておらず、必要性を感じていない受け身のお客様）

各属性について次を作る：
- opening: 第一声（4〜6個）。decidedは具体的（例「コーティングを検討していて、見積ももらったんですが」）、
  undecidedは受け身・曖昧（例「特に決めてないんですけど、一応話だけ…」「まだ何も考えてなくて」）。
- concerns: 抱えがちな本音・不安（5〜6個、短文）
- objections: 断り・保留の言い回し（5〜6個、口語。例「主人と相談して…」「一旦持ち帰って…」）
- verbal_tics: 口ぐせ・相槌（4〜5個。例「うーん」「なるほど」「そうですね…」）

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
