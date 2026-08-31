"""相棒のドット絵のテスト。

絵そのものの良し悪しは目で見るしかないが、「壊れていない」ことは機械で守れる。
"""
import pytest

from core import companion_defs as defs
from core import pixel_sprites as ps

ALL = [(s.id, stage) for s in defs.SPECIES for stage in range(1, defs.STAGE_COUNT + 1)]


@pytest.mark.parametrize("species_id,stage", ALL)
def test_every_stage_draws_a_16x16_picture(species_id, stage):
    for frame in (0, 1):
        rows = ps.sprite(species_id, stage, frame)
        assert len(rows) == ps.GRID
        assert all(len(r) == ps.GRID for r in rows)


@pytest.mark.parametrize("species_id,stage", ALL)
def test_every_stage_actually_has_something_drawn(species_id, stage):
    """空っぽの姿があると、その段階だけ何も見えなくなる。"""
    dots = sum(ch != "." for row in ps.sprite(species_id, stage) for ch in row)
    assert dots >= 8


@pytest.mark.parametrize("species_id,stage", ALL)
def test_only_known_colors_are_used(species_id, stage):
    palette = ps.colors(species_id)
    for frame in (0, 1):
        for row in ps.sprite(species_id, stage, frame):
            for ch in row:
                assert ch == "." or ch in palette


def test_the_two_frames_differ_so_it_moves():
    for s in defs.SPECIES:
        assert ps.sprite(s.id, 5, 0) != ps.sprite(s.id, 5, 1)


def test_it_grows_as_it_levels_up():
    """段階が上がると見た目が大きくなる（育った実感が要る）。"""
    for s in defs.SPECIES:
        small = sum(ch != "." for row in ps.sprite(s.id, 2) for ch in row)
        big = sum(ch != "." for row in ps.sprite(s.id, 8) for ch in row)
        assert big > small, s.id


def test_each_species_looks_different():
    """同じ絵の使い回しをしない（集める意味が無くなる）。"""
    shapes = {s.id: tuple(ps.sprite(s.id, 6)) for s in defs.SPECIES}
    assert len(set(shapes.values())) == len(defs.SPECIES)


def test_drawing_is_stable():
    """毎回同じ絵になる（描くたびに姿が変わると相棒に見えない）。"""
    assert ps.sprite("tori", 4) == ps.sprite("tori", 4)


@pytest.mark.parametrize("stage", [-5, 0, 99])
def test_out_of_range_stage_does_not_crash(stage):
    assert len(ps.sprite("tori", stage)) == ps.GRID


def test_unknown_species_falls_back_instead_of_crashing():
    assert len(ps.sprite("いない種族", 3)) == ps.GRID
