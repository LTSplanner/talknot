"""リマインド文面のローテーションのテスト。

同じ文面が続くと読み飛ばされるので、人ごと・日ごとに切り替える。
再送しても文面が変わらない（＝日付と宛先だけで決まる）ことも守る。
"""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "send_roleplay_reminders",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "send_roleplay_reminders.py",
)
reminders_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reminders_script)

_MESSAGES = reminders_script._MESSAGES
_message_for = reminders_script._message_for
_variant_index = reminders_script._variant_index

ALICE = "amoritani@life-time-support.com"
BOB = "toshima@life-time-support.com"


def test_same_person_gets_a_different_message_the_next_day():
    """2日つづけて同じ文面にならない（毎日1つずつ進む）。"""
    for day in range(1, 15):
        a = _variant_index(ALICE, f"2026-08-{day:02d}")
        b = _variant_index(ALICE, f"2026-08-{day + 1:02d}")
        assert a != b


def test_people_get_different_messages_on_the_same_day():
    """同じ日でも人によって文面が違う。"""
    assert _variant_index(ALICE, "2026-08-04") != _variant_index(BOB, "2026-08-04")


def test_same_person_same_day_is_stable():
    """再実行・再送しても文面が変わらない（実行ごとに変わるhashを使わない）。"""
    first = _message_for(ALICE, {}, "2026-08-04")
    assert first == _message_for(ALICE, {}, "2026-08-04")


def test_all_variants_are_used_over_time():
    """一定期間まわせば全種類が使われる（死に文面をつくらない）。"""
    import datetime as dt
    start = dt.date(2026, 8, 1)
    seen = {_variant_index(ALICE, str(start + dt.timedelta(days=i)))
            for i in range(len(_MESSAGES) + 2)}
    assert seen == set(range(len(_MESSAGES)))


def test_variants_are_all_different():
    """同じ文面を二重に登録しない（増やすときの取り違え防止）。"""
    assert len(set(_MESSAGES)) == len(_MESSAGES)


def test_rotation_covers_about_a_month():
    """1ヶ月ぶん回せるだけの種類を持たせる（慣れて読み飛ばされないように）。"""
    assert len(_MESSAGES) >= 30


def test_message_has_name_and_link():
    text = _message_for(ALICE, {ALICE: "森谷淳美"}, "2026-08-04")
    assert "森谷淳美さん" in text
    assert text.endswith("https://talknot-lts.streamlit.app")


def test_message_falls_back_to_email_local_part():
    """表示名が取れなかった人にも送れる（送信を止めない）。"""
    assert "amoritaniさん" in _message_for(ALICE, {}, "2026-08-04")


def test_every_variant_keeps_the_daily_nudge():
    """どの文面も「継続の後押し」と「負担を下げる言葉」の両方を持つ。

    どちらかが欠けると、催促だけの文面になって続かない。文面を足すときも
    この2つは必ず入れる。
    """
    # 負担を下げる言い回し（実際に使っている表現をそのまま並べている）
    soft = ("大丈夫", "気合いは要りません", "完璧じゃなくていい", "うまくいかなくても",
            "だけでも意味があります", "短くていい", "5分で足ります", "十分", "だけ時間",
            "上手さは要りません", "気にしなくて", "だけでも")
    # 継続を促す言い回し
    daily = ("毎日", "今日", "1日")
    for body in _MESSAGES:
        assert any(w in body for w in soft), f"負担を下げる言葉が無い: {body}"
        assert any(w in body for w in daily), f"継続の後押しが無い: {body}"


def test_every_variant_is_short_enough_to_read():
    """長いと読み飛ばされる。リンクを除いて160字までに収める。"""
    for body in _MESSAGES:
        assert len(body) <= 160, f"{len(body)}字と長い: {body}"


def test_bad_date_does_not_crash():
    """日付が壊れていても送信は止めない。"""
    assert _message_for(ALICE, {}, "") .startswith("🎙️")


def test_streak_line_appears_only_when_the_record_is_alive():
    """続いている人にだけ『今日やれば◯日』を添える。"""
    assert reminders_script._streak_line(0) == ""
    assert "2 日" in reminders_script._streak_line(1)
    assert "6 日" in reminders_script._streak_line(5)


def test_message_includes_the_streak():
    text = _message_for(ALICE, {ALICE: "森谷淳美"}, "2026-08-04", streak=4)
    assert "今日やれば 5 日つづけて達成です。" in text
    assert text.endswith("https://talknot-lts.streamlit.app")


def test_message_without_streak_has_no_extra_line():
    text = _message_for(ALICE, {ALICE: "森谷淳美"}, "2026-08-04", streak=0)
    assert "つづけて達成" not in text
