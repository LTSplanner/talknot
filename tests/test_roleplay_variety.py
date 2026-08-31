"""ロープレの『揺らぎ』のテスト。

守りたいのは2つ。
  - 毎回ちがう（暗記できない）
  - 1回のロープレの中では変わらない（画面のセリフ・音声・AI評価がずれない）
"""
import pytest

from core import roleplay_variety as V


class TestItStaysFixedWithinOneSession:
    def test_same_seed_gives_the_same_customer(self):
        """同じ seed なら何度呼んでも同じ。リランで相手が変わると評価が成立しない。"""
        a, b = V.draw(1234, 6, 1), V.draw(1234, 6, 1)
        assert a == b

    def test_applying_twice_gives_the_same_lines(self):
        turns = [{"customer": f"c{i}", "hint": ""} for i in range(6)]
        v = V.draw(99, len(turns), 2)
        assert [t["customer"] for t in V.apply(turns, v)] == \
               [t["customer"] for t in V.apply(turns, v)]

    def test_apply_does_not_touch_the_original_turns(self):
        """台本そのものを書き換えない（別単元に汚れが残らない）。"""
        turns = [{"customer": "c0", "hint": "h0"}, {"customer": "c1", "hint": "h1"}]
        V.apply(turns, V.draw(5, 2, 2))
        assert turns == [{"customer": "c0", "hint": "h0"}, {"customer": "c1", "hint": "h1"}]


class TestItIsDifferentEveryTime:
    def test_many_different_customers_appear(self):
        """暗記できない程度に組み合わせがある。"""
        seen = {(v.temper, v.companion, v.concern)
                for v in (V.draw(s, 6, 1) for s in range(300))}
        assert len(seen) >= 50

    def test_missions_rotate(self):
        seen = {V.draw(s, 6, 1).mission for s in range(200)}
        assert len(seen) == len(V.MISSIONS)

    def test_adlib_position_varies(self):
        positions = {v.adlibs[0][0] for v in (V.draw(s, 6, 1) for s in range(200))
                     if v.adlibs}
        assert len(positions) >= 3


class TestAdlibs:
    def test_the_opening_line_is_never_replaced(self):
        """第一声は単元の学びどころ。アドリブで潰さない。"""
        turns = [{"customer": "台本の第一声", "hint": ""} for _ in range(6)]
        for s in range(100):
            out = V.apply(turns, V.draw(s, len(turns), 2))
            assert out[0]["customer"] == "台本の第一声"

    def test_hard_units_get_more_interruptions(self):
        assert len(V.draw(7, 8, 2).adlibs) > len(V.draw(7, 8, 1).adlibs)

    def test_adlibs_are_marked_so_the_screen_can_show_them(self):
        out = V.apply([{"customer": "c", "hint": ""} for _ in range(5)], V.draw(3, 5, 2))
        assert any(t.get("adlib") for t in out)

    def test_every_adlib_has_a_way_out(self):
        """横やりを出すだけでは練習にならない。返し方の例を必ず添える。"""
        for text, hint in V.ADLIBS:
            assert text.strip() and "例）" in hint

    def test_adlibs_are_not_duplicated(self):
        assert len({t for t, _ in V.ADLIBS}) == len(V.ADLIBS)

    def test_one_turn_scenario_does_not_crash(self):
        """ターンが1つしかない単元でも落ちない（割り込む場所が無いだけ）。"""
        turns = [{"customer": "c0", "hint": ""}]
        assert len(V.apply(turns, V.draw(1, 1, 2))) == 1

    def test_empty_scenario_does_not_crash(self):
        assert V.apply([], V.draw(1, 0, 1)) == []


class TestCardText:
    def test_card_line_shows_all_three_axes(self):
        v = V.draw(42, 6, 1)
        for _, label, _ in (v.temper, v.companion, v.concern):
            assert label in v.card_line

    def test_acting_note_tells_how_to_play_the_customer(self):
        v = V.draw(42, 6, 1)
        assert v.acting_note.count("\n") == 2

    @pytest.mark.parametrize("axis", [V.TEMPERS, V.COMPANIONS, V.CONCERNS])
    def test_axis_entries_are_complete(self, axis):
        for icon, label, note in axis:
            assert icon and label and note
