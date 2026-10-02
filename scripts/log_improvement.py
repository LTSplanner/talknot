"""ご意見箱の要望を「いつ・どう直したか」としてスプレッドシートに記録する。

ご意見箱の投稿はアプリのシートに溜まるが、それを**どう直したか**は残っていなかった。
ホストが「何がいつどう変わったか」を追えるよう、改善1件につき1行を追記する。

書き込む先（進捗管理用の専用スプレッドシート = settings.IMPROVEMENT_SHEET_ID）:
  - 「修正ログ（全体）」タブ … すべての改善（日付 / 改善内容 / ビフォー / アフター / 備考）
  - 「修正ログ（影山さん）」タブ … 依頼者が s.kageyama@ のときだけ、同じ行の控えを残す

使い方（GitHub Actions の log-improvement から実行するのが基本）:
    python scripts/log_improvement.py \
      --what "ロープレの採点をカンペ基準にした" \
      --before "カンペ通りに言っても『こう言えたら』と直され、0点も出ていた" \
      --after "カンペ通りなら3点以上。0点は出さない。相槌への指摘もやめた" \
      --note "安栗さん・影山さんからの指摘" --sender s.kageyama@life-time-support.com
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys

from config import settings
from services import sheets_knowledge

JST = _dt.timezone(_dt.timedelta(hours=9))


def today_jst() -> str:
    return _dt.datetime.now(JST).strftime("%Y-%m-%d")


def build_row(what: str, before: str, after: str, note: str = "",
              date: str = "") -> list[str]:
    """5列（日付・改善内容・ビフォー・アフター・備考）の1行を作る。"""
    return [date or today_jst(), what.strip(), before.strip(), after.strip(), note.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="改善履歴を1行追記する")
    ap.add_argument("--what", required=True, help="改善内容")
    ap.add_argument("--before", default="", help="直す前はどうだったか")
    ap.add_argument("--after", default="", help="直した後どうなったか")
    ap.add_argument("--note", default="", help="備考（依頼者・経緯など）")
    ap.add_argument("--date", default="", help="日付（既定は今日・JST）")
    ap.add_argument("--sender", default="", help="要望をくれた人のメール")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    row = build_row(args.what, args.before, args.after, args.note, args.date)
    personal = sheets_knowledge.personal_tab_for(args.sender)
    print("記録する行:")
    for name, value in zip(["日付", "改善内容", "ビフォー", "アフター", "備考"], row):
        print(f"  {name}: {value}")
    print(f"書き込み先: {settings.IMPROVEMENT_TAB}"
          f"{'、' + personal if personal else ''}")

    if args.dry_run:
        print("--dry-run のため書き込みません。")
        return 0
    if not sheets_knowledge.configured():
        print("シートが未設定のため書き込めません。")
        return 1
    written = sheets_knowledge.append_improvement(row, sender=args.sender)
    print(f"💾 追記しました: {'、'.join(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
