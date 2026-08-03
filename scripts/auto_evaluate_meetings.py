"""初回商談の録画を自動評価する定期バッチ（無人・完了通知なし）。

流れ:
  1. 各プランナー（settings.TARGET_ACCOUNTS）を DWD サービスアカウントで impersonate。
  2. google_calendar.list_meetings() で直近の商談予定を取得し、
     core.auto_eval.is_first_meeting() で「初回商談」だけに絞る。
  3. storage.list_evaluations() の label から評価済み案件番号を集め、二重評価を防ぐ。
  4. core.auto_eval.select_targets() で『古い未処理から順・1日◯件まで』に絞る。
  5. 選ばれた各件を find_recording() で録画照合 → 見つかったものだけ
     download_to_path() で一時保存 → gemini_analyzer.analyze() → storage.save_evaluation()。
     録画未検出はスキップ（次回に持ち越し）。失敗は fail_evaluation() して継続。

方針（Actions を赤くしない・無料枠とデータを守る）:
  - 認証情報（SA鍵）や取得に失敗したら、評価せず exit 0。
  - --dry-run では ダウンロード/評価/保存をせず、評価予定リストと件数だけ表示。
  - 動画解析は1件ずつ直列（メモリ保護）。一時ファイルは必ず削除する。

実行 env:
  CALENDAR_SA_JSON（DWD SAの鍵JSON文字列）または GOOGLE_SERVICE_ACCOUNT_FILE（鍵ファイルのパス）
  GEMINI_API_KEY（動画解析）
  KNOWLEDGE_SHEET_ID / KNOWLEDGE_SA_JSON（評価履歴・ナレッジの永続化。無ければローカル）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

from config import settings
from core.auto_eval import case_ids_in, is_first_meeting, select_targets
from core.meeting_context import build_meeting_context
from core.progress import latest_one_point
from services import gemini_analyzer, google_calendar, google_drive, storage

# DWD で対象者を impersonate するときのスコープ（読み取りのみ）。
_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _calendar_sa_info() -> dict | None:
    """DWD SA の鍵情報（JSONのdict）を env から読む。

    CALENDAR_SA_JSON（JSON文字列）を優先し、無ければ GOOGLE_SERVICE_ACCOUNT_FILE
    （鍵ファイルのパス）を使う。どちらも無効なら None（＝評価せず終了）。
    """
    raw = (os.getenv("CALENDAR_SA_JSON") or "").strip()
    if raw:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    path = (settings.GOOGLE_SERVICE_ACCOUNT_FILE or "").strip()
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    return None


def _creds_for(planner: str, sa_info: dict):
    """DWD SA で planner を impersonate した Credentials を作る（ネットワークなし）。"""
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        sa_info, scopes=_SCOPES
    ).with_subject(planner)


def _collect(targets: list[str], sa_info: dict, lookback_days: int):
    """全プランナーの『初回商談』候補と、評価済み案件番号の集合を集める。

    戻り値: (candidates, done_case_ids)。
    候補は {planner, case_id, summary, start, start_date}。
    """
    candidates: list[dict] = []
    done: set[str] = set()

    for planner in targets:
        # 1) カレンダーから初回商談を集める
        try:
            creds = _creds_for(planner, sa_info)
            meetings = google_calendar.list_meetings(
                creds, days_back=lookback_days, days_ahead=0, deals_only=True
            )
        except Exception as e:  # noqa: BLE001 取得失敗はその人だけスキップ
            print(f"  カレンダー取得失敗（スキップ）: {planner}: {str(e)[:120]}")
            meetings = []

        for m in meetings:
            if not is_first_meeting(m.get("summary", "")):
                continue
            # 稼働開始日より前の過去分は自動評価しない（本日分から）
            if settings.AUTO_EVAL_START_DATE and \
                    m.get("start_date", "") < settings.AUTO_EVAL_START_DATE:
                continue
            candidates.append({
                "planner": planner,
                "case_id": m.get("case_id", ""),
                "summary": m.get("summary", ""),
                "start": m.get("start", ""),
                "start_date": m.get("start_date", ""),
            })

        # 2) 既存の評価履歴（done/error/processing 問わず）の label から案件番号を拾い、
        #    二重処理・無限リトライを防ぐ。
        try:
            for rec in storage.list_evaluations(planner):
                done |= case_ids_in(rec.get("label", ""))
        except Exception as e:  # noqa: BLE001 履歴が読めなくても評価自体は進める
            print(f"  評価履歴の読込み失敗（重複除外に反映されず）: {planner}: {str(e)[:120]}")

    return candidates, done


def _process_one(
    candidate: dict, creds, reference_talk, knowledge, planner_name: str = ""
) -> str:
    """1件を録画照合→DL→評価→保存する。結果を短い文字列で返す（ログ用）。

    録画未検出は保存せずスキップ（次回持ち越し）。失敗は fail_evaluation して継続。
    一時ファイルは必ず削除する。planner_name（Workspaceの表示名）と予定タイトルから
    確定情報を組み立てて渡し、固有名詞の当て字（例「安栗」→「アングルリ」）を防ぐ。
    """
    planner = candidate["planner"]
    summary = candidate["summary"]
    rec = google_calendar.find_recording(creds, summary, candidate.get("start_date", ""))
    if not rec:
        return "録画なし（次回持ち越し）"

    context = build_meeting_context(
        summary, planner_name=planner_name, meeting_date=candidate.get("start_date", "")
    )

    fd, tmp = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        google_drive.download_to_path(creds, rec["id"], tmp)
        # 前回この人に出した「1点」を渡し、できたかの答え合わせから始めさせる。
        try:
            previous = latest_one_point(storage.list_evaluations(planner))
        except Exception:  # noqa: BLE001 履歴が読めなくても評価は続ける
            previous = None
        result = gemini_analyzer.analyze(
            tmp, reference_talk, knowledge, context, previous)
        storage.save_evaluation(planner, result, label=summary)
        return "評価を保存"
    except Exception as e:  # noqa: BLE001 1件の失敗で全体を止めない
        job_id = time.strftime("%Y%m%d_%H%M%S")
        try:
            storage.fail_evaluation(planner, job_id, str(e), label=summary)
        except Exception:  # noqa: BLE001 記録失敗も本体を止めない
            pass
        return f"失敗: {str(e)[:120]}"
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="初回商談の録画を自動評価する")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ダウンロード/評価/保存をせず、評価予定リストと件数だけ表示",
    )
    args = parser.parse_args()

    targets = settings.TARGET_ACCOUNTS
    limit = settings.AUTO_EVAL_DAILY_LIMIT
    lookback = settings.AUTO_EVAL_LOOKBACK_DAYS
    print(f"対象 {len(targets)} 名 / 1日上限 {limit} 件 / 遡り {lookback} 日")

    sa_info = _calendar_sa_info()
    if sa_info is None:
        print("SA鍵が未設定（CALENDAR_SA_JSON / GOOGLE_SERVICE_ACCOUNT_FILE）。評価せず終了。")
        return 0

    candidates, done = _collect(targets, sa_info, lookback)
    selected = select_targets(candidates, done, limit)
    print(f"初回商談の候補 {len(candidates)} 件 / 評価済み {len(done)} 案件 "
          f"/ 今回の対象 {len(selected)} 件")

    if not selected:
        print("評価する初回商談はありません。")
        return 0

    # 評価に使う模範トーク・ナレッジは本番実行時のみ読む（dry-run では読まない）。
    reference_talk = None
    knowledge = None
    if not args.dry_run:
        try:
            reference_talk = storage.get_reference_talk()
            knowledge = storage.get_knowledge_base()
        except Exception as e:  # noqa: BLE001 参照が無くても評価は続行
            print("模範トーク/ナレッジの読込みに失敗（無しで続行）:", str(e)[:120])

    creds_cache: dict[str, object] = {}
    name_cache: dict[str, str] = {}

    def _creds(planner: str):
        if planner not in creds_cache:
            creds_cache[planner] = _creds_for(planner, sa_info)
        return creds_cache[planner]

    def _planner_name(planner: str) -> str:
        """営業担当の氏名（Workspaceの表示名）。取れなければ空文字のまま進める。"""
        if planner not in name_cache:
            name_cache[planner] = google_drive.get_display_name(_creds(planner))
        return name_cache[planner]

    processed = 0
    for c in selected:
        planner = c["planner"]
        try:
            if args.dry_run:
                # 録画の有無だけ確認して表示（DL/評価/保存はしない）。
                rec = google_calendar.find_recording(
                    _creds(planner), c["summary"], c.get("start_date", "")
                )
                found = "あり" if rec else "なし"
                ctx = build_meeting_context(
                    c["summary"], _planner_name(planner), c.get("start_date", ""))
                print(f"  [dry-run] {planner} / {c['case_id']} / {c['summary']} / "
                      f"録画: {found}")
                print(f"            確定情報 → 担当:{ctx['planner_name'] or '（不明）'} "
                      f"/ お客様:{ctx['customer_name'] or '（不明）'} "
                      f"/ 物件:{ctx['property_name'] or '（不明）'}")
                continue
            outcome = _process_one(
                c, _creds(planner), reference_talk, knowledge, _planner_name(planner))
            if outcome == "評価を保存":
                processed += 1
            print(f"  {planner} / {c['case_id']} / {c['summary']} → {outcome}")
        except Exception as e:  # noqa: BLE001 想定外でも次の人へ
            print(f"  想定外エラー（スキップ）: {planner} / {c['case_id']}: {str(e)[:120]}")

    if not args.dry_run:
        print(f"評価を保存した件数: {processed} 件")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 何が起きても Actions を赤くしない
        print("想定外エラー（無視して終了）:", str(e)[:200])
        sys.exit(0)
