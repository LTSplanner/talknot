"""長い録画を区間に分けて解析し、結果を束ねる処理のテスト。

3時間の商談を丸ごと渡すと冒頭5分ぶんの指摘しか返らなかったため、区間に分ける。
時刻の付け替えを間違えると全区間の指摘が 00:xx に潰れるので、そこを厚く固定する。
"""
from core import chunking, prompts


def test_short_recording_is_not_split():
    """45分以内は1回で最後まで読めるので分割しない。"""
    assert chunking.plan_chunks(20 * 60) == [(0, 1200)]
    assert chunking.plan_chunks(45 * 60) == [(0, 2700)]


def test_long_recording_is_split_into_30min_chunks():
    got = chunking.plan_chunks(90 * 60)
    assert got == [(0, 1800), (1800, 3600), (3600, 5400)]


def test_three_hour_recording():
    got = chunking.plan_chunks(180 * 60 + 24)
    assert len(got) == 6
    assert got[0] == (0, 1800)
    assert got[-1] == (9000, 10824)     # 末尾は端数ぶん長い


def test_tiny_tail_is_merged_into_the_previous_chunk():
    """末尾が数十秒だけの区間を作らない（文脈が足りず評価にならない）。"""
    got = chunking.plan_chunks(60 * 60 + 90)   # 60分90秒
    assert got == [(0, 1800), (1800, 3690)]
    assert all(end - start >= 5 * 60 for start, end in got)


def test_empty_duration_gives_no_chunks():
    assert chunking.plan_chunks(0) == []
    assert chunking.plan_chunks(None) == []


def test_timestamp_roundtrip():
    assert chunking.format_timestamp(0) == "00:00"
    assert chunking.format_timestamp(95) == "01:35"
    assert chunking.format_timestamp(3600) == "1:00:00"
    assert chunking.parse_timestamp("01:35") == 95
    assert chunking.parse_timestamp("1:00:00") == 3600
    assert chunking.parse_timestamp("なし") is None


def test_shift_moves_timestamps_to_their_place_in_the_whole():
    """区間内の経過時間を、録画全体での位置に直す。"""
    part = {
        "feedback": [{"timestamp": "02:10", "after": "こう言う"}],
        "hidden_needs": [{"timestamp": "12:00", "inferred_need": "不安"}],
    }
    got = chunking.shift_timestamps(part, 3600)          # 1時間目の区間
    assert got["feedback"][0]["timestamp"] == "1:02:10"
    assert got["hidden_needs"][0]["timestamp"] == "1:12:00"


def test_shift_leaves_other_text_alone():
    """時刻でない文字列（セリフ・見出し）は書き換えない。"""
    part = {"summary": "12:00 に昼食の話が出た", "one_point": {"headline": "02:10"}}
    got = chunking.shift_timestamps(part, 600)
    assert got["summary"] == "12:00 に昼食の話が出た"     # 文中の数字は触らない
    assert got["one_point"]["headline"] == "12:10"       # 単独の時刻は直す


def test_no_shift_for_the_first_chunk():
    part = {"feedback": [{"timestamp": "02:10"}]}
    assert chunking.shift_timestamps(part, 0) == part


def test_merge_concatenates_scenes_and_averages_scores():
    parts = [
        {"feedback": [{"timestamp": "02:10"}], "hidden_needs": [{"inferred_need": "a"}],
         "scores": [{"key": "emotion_catch", "sales_score": 4, "sales_comment": "良い"}],
         "johari": {"open_pct": 40, "blind_pct": 30, "hidden_pct": 20, "unknown_pct": 10}},
        {"feedback": [{"timestamp": "35:00"}], "hidden_needs": [{"inferred_need": "b"}],
         "scores": [{"key": "emotion_catch", "sales_score": 2, "sales_comment": "惜しい"}],
         "johari": {"open_pct": 60, "blind_pct": 20, "hidden_pct": 10, "unknown_pct": 10}},
    ]
    got = chunking.merge_results(parts)
    assert [f["timestamp"] for f in got["feedback"]] == ["02:10", "35:00"]
    assert len(got["hidden_needs"]) == 2
    assert got["scores"][0]["sales_score"] == 3          # (4+2)/2
    assert got["johari"]["open_pct"] == 50               # (40+60)/2
    assert got["johari"]["blind_pct"] == 25


def test_merge_does_not_pick_a_partial_one_point():
    """1ポイント・振り返りは区間の寄せ集めにしない（全体で決め直す）。"""
    parts = [{"one_point": {"headline": "冒頭だけの指摘"}, "summary": "前半の話"},
             {"one_point": {"headline": "後半だけの指摘"}, "summary": "後半の話"}]
    got = chunking.merge_results(parts)
    assert "one_point" not in got
    assert "summary" not in got


def test_merge_of_a_single_part_is_unchanged():
    part = {"feedback": [{"timestamp": "01:00"}], "one_point": {"headline": "x"}}
    assert chunking.merge_results([part]) == part


def test_segment_prompt_tells_the_model_it_is_a_slice():
    """区間だけ渡すと『冒頭』と勘違いするので、どこを見ているか明示する。"""
    p = prompts.build_evaluation_prompt(segment=(3600, 5400, 10824))
    assert "1:00:00 〜 1:30:00" in p
    assert "全体は 3:00:24" in p
    assert "この映像の先頭を 00:00 とした経過時間" in p
    assert "挨拶や自己紹介が無くても不自然ではありません" in p
