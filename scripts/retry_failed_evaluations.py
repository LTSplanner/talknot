"""失敗した評価を、後からやり直して完了させる（定期実行）。

■ なぜ必要か
ロープレはやったのに、AIの混雑（"This model is currently experiencing high demand."）や
アプリの再起動で評価だけが失敗することがある。プランナーからすれば
「せっかくやったのに、やっていないことにされる」ので負担が大きい。

評価を始めるとき、録音は先に Gemini へ預けて、そのファイルURIを記録に
残してある（retry_payload）。この処理はそれを拾って、**録り直さずに**評価をやり直す。

■ 負荷をかけない工夫（時間はかかってよい）
- 1回の実行で処理するのは既定3件まで。1件ごとに30秒あける
- やり直すたびに thinking の量を減らす（8192 → 4096 → 2048）。
  混雑時は軽いリクエストの方が通る
- 5回やっても駄目なら諦める（延々と枠を使わない）
- 預けた録音は48時間で消えるため、それより古いものは対象外にして
  「録り直してください」と分かる文言を残す

使い方:
    python scripts/retry_failed_evaluations.py            # 実行
    python scripts/retry_failed_evaluations.py --dry-run  # 対象の確認だけ
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time

from config import settings
from core import meeting_context
from services import gemini_analyzer, sheets_knowledge, storage, usage_log

# 1回の実行で処理する上限（無料枠を使い切らないため）。
MAX_PER_RUN = 3
# 1件ごとの間隔（秒）。まとめて投げると混雑を悪化させる。
GAP_SEC = 30
# 何回までやり直すか。
MAX_ATTEMPTS = 5
# やり直すたびに軽くする thinking の量。
THINKING_LADDER = [8192, 4096, 2048, 1024, 512]
# 預けた録音の有効期限（Files API は48時間）。少し手前で打ち切る。
PAYLOAD_TTL_HOURS = 44


def _payload_of(rec: dict) -> dict | None:
    raw = (rec.get("retry_payload") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("audio_files") else None


def _age_hours(saved_at: str) -> float:
    try:
        t = _dt.datetime.strptime(saved_at, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return 0.0
    return (_dt.datetime.now() - t).total_seconds() / 3600


def find_targets(records: list[dict]) -> list[dict]:
    """やり直す対象（失敗 or 長く処理中のまま で、材料が残っているもの）。"""
    out = []
    for rec in records:
        if rec.get("status") not in ("error", "processing"):
            continue
        payload = _payload_of(rec)
        if not payload:
            continue
        if int(payload.get("attempts", 0)) >= MAX_ATTEMPTS:
            continue
        if _age_hours(rec.get("saved_at", "")) > PAYLOAD_TTL_HOURS:
            continue
        # 「処理中」は、まだアプリ側で走っている可能性があるので少し待ってから拾う
        if rec.get("status") == "processing" and _age_hours(rec.get("saved_at", "")) < 1:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("saved_at", ""))
    return out


def _retry_one(rec: dict, payload: dict) -> bool:
    """1件やり直す。成功したら True。"""
    attempts = int(payload.get("attempts", 0))
    budget = THINKING_LADDER[min(attempts, len(THINKING_LADDER) - 1)]
    email, job_id = rec.get("user_email", ""), rec.get("job_id", "")
    label = rec.get("label", "")
    print(f"  やり直し {attempts + 1} 回目（thinking={budget}）: {email} / {label}")

    payload["attempts"] = attempts + 1
    try:
        result = gemini_analyzer.analyze_roleplay(
            [], payload.get("scenario_lines") or [],
            storage.get_talk_script() or None,
            storage.get_knowledge_base(),
            focus=payload.get("focus"),
            persona=storage.get_customer_persona(),
            meeting_context=meeting_context.build_meeting_context(
                "", payload.get("planner_name", "")),
            audio_files=payload.get("audio_files"),
            thinking_budget=budget,
        )
    except Exception as exc:  # noqa: BLE001 次の実行でまた拾う
        print(f"    → まだ失敗: {str(exc)[:120]}")
        storage.fail_evaluation(
            email, job_id,
            f"評価をやり直しています（{payload['attempts']}回目）。"
            "録り直しは不要です。しばらくお待ちください。",
            label, retry_payload=json.dumps(payload, ensure_ascii=False))
        return False

    storage.finish_evaluation(email, job_id, result, label)
    storage.append_knowledge(result.knowledge)
    usage_log.log("roleplay", user_email=email, ok=True, source="retry")
    print("    → 完了")
    return True


def _give_up(rec: dict, payload: dict | None) -> None:
    """材料が期限切れ・回数超過のとき、本人に分かる文言に書き換える。"""
    storage.fail_evaluation(
        rec.get("user_email", ""), rec.get("job_id", ""),
        "評価を完了できませんでした（AIの混雑が続いたため）。"
        "お手数ですが、もう一度ロープレを実施してください。",
        rec.get("label", ""), retry_payload="")


def verdict(rec: dict) -> str:
    """その失敗を今後どうすれば片づくかを一言で返す（一覧表示用）。"""
    from core import auto_eval, badges

    if _payload_of(rec):
        return "自動でやり直します（録り直し不要）"
    if badges.is_roleplay(rec):
        return "録音が残っていないため、もう一度実施が必要"
    if auto_eval.is_first_meeting(rec.get("label", "")):
        return "初回商談なので自動評価が再挑戦します"
    return "対象外の商談なので、必要なら画面から手動で再評価"


def _report(records: list[dict]) -> None:
    """失敗している記録を人ごとに並べ、それぞれ今後どうなるかを表示する。"""
    from core import progress

    visible = progress.hide_resolved_errors(records)
    failed = [r for r in visible if r.get("status") in ("error", "processing")]
    print(f"\n--- 未完了の記録 {len(failed)} 件（後で成功した分は除く）---")
    by_person: dict[str, list[dict]] = {}
    for rec in sorted(failed, key=lambda r: r.get("saved_at", "")):
        by_person.setdefault(rec.get("user_email", "（不明）"), []).append(rec)
    for email, rows in sorted(by_person.items()):
        print(f"  {email}: {len(rows)} 件")
        for rec in rows:
            print(f"    {rec.get('saved_at')} {rec.get('label')[:40]}"
                  f"\n      → {verdict(rec)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="失敗した評価を後からやり直す")
    ap.add_argument("--dry-run", action="store_true", help="対象の確認だけ")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = ap.parse_args()

    if not sheets_knowledge.configured():
        print("評価履歴シートが未設定のため何もしません。")
        return 0

    records = sheets_knowledge.load_evaluations()
    targets = find_targets(records)
    print(f"やり直し対象: {len(targets)} 件（今回処理するのは最大 {args.limit} 件）")

    # 期限切れ・回数超過のものは、本人に分かる文言へ書き換えておく
    for rec in records:
        payload = _payload_of(rec)
        if not payload or rec.get("status") not in ("error", "processing"):
            continue
        expired = _age_hours(rec.get("saved_at", "")) > PAYLOAD_TTL_HOURS
        used_up = int(payload.get("attempts", 0)) >= MAX_ATTEMPTS
        if expired or used_up:
            print(f"  諦め: {rec.get('user_email')} / {rec.get('label')}"
                  f"（{'期限切れ' if expired else '回数超過'}）")
            if not args.dry_run:
                _give_up(rec, payload)

    if args.dry_run:
        for rec in targets[: args.limit]:
            print(f"  [dry-run] {rec.get('saved_at')} {rec.get('user_email')} "
                  f"{rec.get('label')}")
        _report(records)
        return 0

    done = 0
    for i, rec in enumerate(targets[: args.limit]):
        if i:
            time.sleep(GAP_SEC)     # まとめて投げず、混雑を悪化させない
        payload = _payload_of(rec)
        if payload and _retry_one(rec, payload):
            done += 1
    print(f"完了 {done} 件 / 試行 {min(len(targets), args.limit)} 件")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 定期実行を赤くしない
        print("想定外エラー（無視して終了）:", str(e)[:200])
        sys.exit(0)
