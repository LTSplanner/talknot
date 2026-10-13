"""応用⑤「実践スキル」単元（決める力・広げる力）の形を確かめる。"""
import re

from scripts.build_roleplay_scenarios import (
    CLOSE_FOCUS,
    CLOSE_UNITS,
    EXPAND_FOCUS,
    EXPAND_UNITS,
)


def _units():
    return CLOSE_UNITS + EXPAND_UNITS


def test_ids_are_unique():
    ids = [u["id"] for u in _units()]
    assert len(ids) == len(set(ids))


def test_every_turn_has_customer_and_hint():
    for u in _units():
        assert 3 <= len(u["turns"]) <= 5, u["id"]
        for t in u["turns"]:
            assert t["customer"].strip()
            assert t["hint"].strip()


def test_focus_names_the_skill():
    assert "決める力" in CLOSE_FOCUS
    assert "広げる力" in EXPAND_FOCUS


def test_inspection_fee_is_the_official_price():
    # 内覧会同行の料金は 49,500円（税込）だけを使う（ほかの値が混ざらない）
    text = "\n".join(t["hint"] for u in _units() for t in u["turns"]) + CLOSE_FOCUS
    fees = set(re.findall(r"([0-9]{2},[0-9]{3})円", text))
    assert "49,500" in fees
    assert not fees & {"45,000", "50,000"}
