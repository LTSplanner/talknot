"""相棒キャラクター（1人1体を選んで育てる）のテスト。

守りたいのは3つ。
  - 育つのは選んでいる1体だけ（乗り換えても前の子は姿を保つ）
  - すぐには育ちきらない（最終段階まで年単位ではなく半年ほど、ただし数十本では届かない）
  - 間が空いても退化・消滅しない（叱らない設計）
"""
import datetime as dt

import pytest

from core import companion
from core import companion_defs as defs

START = dt.date(2026, 3, 1)
ME = "planner@life-time-support.com"


def _records(n, *, good_every=3, start=START, step=1):
    """n本ぶんのロープレ履歴（step 日おき）。good_every 回に1回は20点以上。"""
    return [
        {
            "user_email": ME,
            "saved_at": f"{start + dt.timedelta(days=i * step)} 10:00",
            "status": "done",
            "label": "🎙️1人ロープレ｜導入",
            "result": {"scores": [
                {"key": "k", "sales_score": 5 if i % good_every == 0 else 3}] * 5},
        }
        for i in range(n)
    ]


def _day(n):
    return str(START + dt.timedelta(days=n))


class TestDefinitions:
    def test_every_species_has_the_same_number_of_stages(self):
        """段階数がそろっていないと Lv.表示（◯/8）が壊れる。"""
        for s in defs.SPECIES:
            assert len(s.stages) == defs.STAGE_COUNT

    def test_thresholds_get_harder_each_stage(self):
        """後半ほど遠くする（すぐ育ちきると育てる楽しみが無くなる）。"""
        gaps = [b - a for a, b in zip(defs.STAGE_THRESHOLDS, defs.STAGE_THRESHOLDS[1:])]
        assert gaps == sorted(gaps)
        assert all(g > 0 for g in gaps)

    def test_species_ids_are_unique(self):
        assert len({s.id for s in defs.SPECIES}) == len(defs.SPECIES)

    def test_no_stage_text_is_empty(self):
        for s in defs.SPECIES:
            for name, icon, desc in s.stages:
                assert name and icon and desc


class TestGrowthIsSlow:
    def test_first_session_hatches_nothing_yet(self):
        """1本で最終形態にはならない（初日は まだ たまご）。"""
        c = companion.compute(_records(1), _day(1))
        assert c.stage == 1

    def test_a_few_sessions_do_not_finish_it(self):
        """30本ではまだ折り返し。段階的に育ちづらくする方針。"""
        c = companion.compute(_records(30), _day(30))
        assert c.stage <= 4
        assert not c.is_max

    def test_final_stage_needs_around_half_a_year_of_daily_practice(self):
        """毎日1本で 120本ではまだ最終ではなく、200本あたりで到達する。"""
        assert not companion.compute(_records(120), _day(120)).is_max
        assert companion.compute(_records(200), _day(200)).is_max

    def test_good_sessions_grow_faster_than_poor_ones(self):
        """回数だけでなく質も見る（20点以上の回にはおまけが付く）。"""
        good = companion.compute(_records(20, good_every=1), _day(20))
        poor = companion.compute(_records(20, good_every=999), _day(20))
        assert good.exp > poor.exp


class TestOnlyTheChosenOneGrows:
    def test_switching_freezes_the_previous_partner(self):
        """乗り換えたら、前の相棒はその時点の姿のまま図鑑に残る。"""
        state = companion.switch_to({}, "neko", _day(20))
        book = {c.species_id: c for c in companion.collection(_records(60), _day(60), state)}
        assert book["tori"].sessions == 20      # 乗り換えまでの20本
        assert book["neko"].sessions == 40      # 乗り換え後の40本
        assert book["neko"].selected and not book["tori"].selected

    def test_others_do_not_grow_at_all(self):
        """選んでいない子には経験値が入らない（同時育成にしない）。"""
        book = companion.collection(_records(60), _day(60), {})
        for c in book:
            if c.species_id != companion_default():
                assert c.exp == 0

    def test_switching_back_keeps_both_records(self):
        """戻しても、それぞれが自分の期間ぶんだけ育つ。"""
        state = companion.switch_to({}, "neko", _day(10))
        state = companion.switch_to(state, "tori", _day(20))
        book = {c.species_id: c for c in companion.collection(_records(30), _day(30), state)}
        assert book["neko"].sessions == 10
        assert book["tori"].sessions == 20

    def test_same_day_switches_do_not_pile_up(self):
        """迷って何度も切り替えても履歴は1日1行（あとで読めなくならない）。"""
        state = companion.switch_to({}, "neko", _day(5))
        state = companion.switch_to(state, "umi", _day(5))
        state = companion.switch_to(state, "hana", _day(5))
        assert len(state["history"]) == 1
        assert state["selected"] == "hana"

    def test_unknown_species_is_ignored(self):
        state = companion.switch_to({}, "ドラゴンもどき", _day(5))
        assert state["selected"] == defs.DEFAULT_ID


def companion_default():
    return defs.DEFAULT_ID


class TestCollectionUnlocks:
    def test_the_first_partner_is_always_available(self):
        book = companion.collection([], _day(0), {})
        assert book[0].unlocked

    def test_later_species_stay_locked_until_earned(self):
        """最初から全部見えていると集める楽しみが無い。"""
        locked = [c for c in companion.collection([], _day(0), {}) if not c.unlocked]
        assert len(locked) >= 3
        assert all(c.unlock_label for c in locked)

    def test_ten_sessions_unlock_the_cat(self):
        book = {c.species_id: c for c in companion.collection(_records(10), _day(10), {})}
        assert book["neko"].unlocked

    def test_locked_species_still_reports_zero_not_error(self):
        book = {c.species_id: c for c in companion.collection([], _day(0), {})}
        assert book["ryu"].exp == 0 and book["ryu"].stage == 1


class TestMoodNeverPunishes:
    def test_long_absence_does_not_reduce_the_stage(self):
        """間が空いても退化しない（叱らない設計）。"""
        near = companion.compute(_records(60), _day(60))
        far = companion.compute(_records(60), _day(400))
        assert far.stage == near.stage
        assert far.exp == near.exp

    def test_mood_changes_with_the_gap(self):
        moods = [companion.compute(_records(10), _day(9 + d)).mood for d in (0, 1, 2, 5, 30)]
        assert moods[0] == "ごきげん"
        assert moods[-1] == "ねむっている"
        assert len(set(moods)) >= 4

    def test_message_invites_the_next_session(self):
        for d in (0, 1, 3, 5, 30):
            msg = companion.compute(_records(10), _day(9 + d)).message
            assert msg and not msg.endswith("？？")

    def test_no_history_starts_from_the_egg(self):
        c = companion.compute([], _day(0))
        assert c.stage == 1 and c.sessions == 0 and c.exp == 0
        assert "1本" in c.message


class TestRobustness:
    @pytest.mark.parametrize("bad", [
        None,
        {"selected": 123},
        {"history": "こわれている"},
        {"history": [{"date": "not-a-date", "id": "tori"}]},
        {"selected": "いない子", "history": [{"id": "neko"}]},
    ])
    def test_broken_state_falls_back_to_the_default_partner(self, bad):
        state = companion.normalize_state(bad)
        assert state["selected"] in defs.BY_ID
        c = companion.compute(_records(5), _day(5), bad)
        assert c.stage >= 1

    def test_meeting_records_do_not_feed_the_partner(self):
        """商談の評価では育たない（ロープレ継続のための仕組みなので）。"""
        meetings = [dict(r, label="🏠商談｜〇〇様") for r in _records(30)]
        assert companion.compute(meetings, _day(30)).exp == 0

    def test_unfinished_records_are_ignored(self):
        pending = [dict(r, status="processing") for r in _records(30)]
        assert companion.compute(pending, _day(30)).exp == 0

    def test_sheet_style_records_also_count(self):
        """シートから読んだ生JSON（result_json）でも育つ。"""
        import json
        rows = [{"user_email": ME, "saved_at": r["saved_at"], "status": "done",
                 "label": r["label"], "result_json": json.dumps(r["result"])}
                for r in _records(10)]
        assert companion.compute(rows, _day(10)).exp > 0

    def test_summary_line_is_short_enough_for_a_chat_message(self):
        c = companion.compute(_records(40), _day(40))
        line = companion.summary_line(c)
        assert len(line) <= 60 and c.name in line


class TestNaming:
    """名前を付けられると愛着がわく。付けた名前は姿が変わっても残る。"""

    def test_a_named_partner_is_called_by_that_name(self):
        state = companion.rename({}, defs.DEFAULT_ID, "ぴよ太")
        c = companion.compute(_records(5), _day(5), state)
        assert c.nickname == "ぴよ太" and c.display_name == "ぴよ太"

    def test_without_a_name_the_stage_name_is_used(self):
        c = companion.compute(_records(5), _day(5), {})
        assert c.nickname == "" and c.display_name == c.name

    def test_the_name_survives_growing_up(self):
        state = companion.rename({}, defs.DEFAULT_ID, "ぴよ太")
        young = companion.compute(_records(5), _day(5), state)
        grown = companion.compute(_records(150), _day(150), state)
        assert young.name != grown.name
        assert grown.nickname == "ぴよ太"

    def test_the_name_survives_switching_partners(self):
        state = companion.rename({}, "tori", "ぴよ太")
        state = companion.switch_to(state, "neko", _day(10))
        state = companion.rename(state, "neko", "みけ")
        book = {c.species_id: c for c in companion.collection(_records(20), _day(20), state)}
        assert book["tori"].nickname == "ぴよ太"
        assert book["neko"].nickname == "みけ"

    def test_names_are_trimmed_and_capped(self):
        state = companion.rename({}, "tori", "　　" + "あ" * 40 + "　")
        assert len(state["names"]["tori"]) == companion.NICKNAME_MAX

    def test_clearing_the_name_goes_back_to_the_stage_name(self):
        state = companion.rename({}, "tori", "ぴよ太")
        state = companion.rename(state, "tori", "   ")
        assert companion.compute([], _day(0), state).display_name == "たまご"

    def test_the_chat_line_uses_the_name(self):
        state = companion.rename({}, defs.DEFAULT_ID, "ぴよ太")
        line = companion.summary_line(companion.compute(_records(40), _day(40), state))
        assert "ぴよ太" in line and len(line) <= 60
