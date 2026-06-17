"""実データでの動画解析スモークテスト（CLI）。

GEMINI_API_KEY を設定したうえで、ローカルの動画/音声ファイルを解析し、
評価結果を整形して表示する。Streamlit を起動せずにAI解析だけ試せる。

    python3 scripts/analyze_video.py /path/to/talk.mp4
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from services import gemini_analyzer, storage  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("使い方: python3 scripts/analyze_video.py <動画/音声ファイル>")
        return 2
    video = argv[1]
    if not Path(video).exists():
        print(f"ファイルが見つかりません: {video}")
        return 2
    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY が未設定です（.env を確認）。")
        return 1

    print(f"解析中: {video}（少し時間がかかります）…")
    result = gemini_analyzer.analyze(video, storage.get_reference_talk())

    print(f"\n総合スコア: {result.total} / {len(settings.EVALUATION_CRITERIA) * 5}\n")
    for c in settings.EVALUATION_CRITERIA:
        s = result.score_for(c.key)
        print(f"  {c.number} {c.title}: {s.score if s else '-'}/5  {s.comment if s else ''}")

    print(f"\n全体講評: {result.summary}\n")
    print("シーン別フィードバック:")
    for f in result.feedback:
        print(f"  ⏱ {f.timestamp} [{f.criterion_key}] {f.emotion_note}")
        print(f"     Before: {f.before}")
        print(f"     After : {f.after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
