"""議事録ナレッジの日次自動更新（GitHub Actions から実行）。

- 知識SA（KNOWLEDGE_SA_JSON）で商談議事録フォルダを読み、新規分を Gemini で抽出。
- 無料枠に当たったら（429）その日はそこで自動停止し、翌日また続きから処理する。
- DWDの強い鍵は不要。GitHub Secrets に KNOWLEDGE_SA_JSON / KNOWLEDGE_SHEET_ID /
  GEMINI_API_KEY を置けば動く（フォルダは知識SAに閲覧共有済み）。

失敗しても Actions を赤くしないよう、原則 exit 0 で終わる。
"""
from __future__ import annotations

import sys

from services import meeting_extractor, storage


def main() -> None:
    if not meeting_extractor.configured():
        print("未設定（KNOWLEDGE_SA / GEMINI_API_KEY / フォルダ）のためスキップ。")
        return
    try:
        remaining, total = meeting_extractor.remaining_count()
    except Exception as e:  # noqa: BLE001
        print("フォルダ参照に失敗:", str(e)[:160])
        return
    processed_before = len(storage.get_processed_meeting_ids())
    print(f"議事録：総数 {total} ／ 処理済み {processed_before} ／ 未処理 {remaining}")
    if remaining == 0:
        print("未処理なし。新しい議事録が増えたら次回処理します。")
        return

    # 無料枠に当たるまで処理（run_extraction は 429 で自動停止する）
    res = meeting_extractor.run_extraction(limit=1000)
    print(f"今回処理 {res['processed']} 件 / 新知見 {res['added']} 件 / "
          f"展開 {res['distilled']} 件 / 残り 約{res['remaining']} 件"
          + ("（無料枠上限で停止・翌日続き）" if res.get("quota") else ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("想定外エラー（無視して終了）:", str(e)[:200])
        sys.exit(0)
