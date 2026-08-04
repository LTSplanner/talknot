"""称号バッジの判定テスト。

バッジは保存せず履歴から毎回計算するので、履歴の並び・内容から指標が
正しく出ることを固定しておく。
"""
from config import settings
from core import badges
from core.badge_defs import ALL_BADGES, MEETING_BADGES, ROLEPLAY_BADGES


def _rec(saved_at, total=15, roleplay=True, status="done", **extra):
    """合計 total 点の評価履歴を1件つくる（5項目に均等配分）。"""
    base, rest = divmod(total, len(settings.EVALUATION_CRITERIA))
    scores = []
    for i, c in enumerate(settings.EVALUATION_CRITERIA):
        scores.append({"key": c.key, "sales_score": base + (1 if i < rest else 0)})
    result = {"scores": scores}
    result.update(extra)
    return {
        "saved_at": saved_at,
        "status": status,
        "label": ("🎙️1人ロープレ｜導入" if roleplay else "◎初回商談 L260722484601　佐藤様"),
        "result": result,
    }


def test_badge_set_is_consistent():
    """称号は随時足していくので総数は固定しない。壊れない条件だけを守る。"""
    assert len(ALL_BADGES) == len(ROLEPLAY_BADGES) + len(MEETING_BADGES)
    assert len({b.id for b in ALL_BADGES}) == len(ALL_BADGES)   # ID の重複なし
    # 同じカテゴリの中で名前・アイコンが被ると、集める楽しみが削がれる
    for badges_in_cat in (ROLEPLAY_BADGES, MEETING_BADGES):
        assert len({b.name for b in badges_in_cat}) == len(badges_in_cat)
        assert len({b.icon for b in badges_in_cat}) == len(badges_in_cat)


def test_roleplay_and_meeting_are_counted_separately():
    """ロープレの回数で商談のバッジは埋まらない。"""
    recs = [_rec(f"2026-08-0{i} 10:00", roleplay=True) for i in range(1, 6)]
    assert badges.compute_metrics(recs, "roleplay")["count"] == 5
    assert badges.compute_metrics(recs, "meeting")["count"] == 0


def test_failed_and_processing_records_do_not_count():
    """失敗・解析中は実施回数に数えない（実施できた分だけ）。"""
    recs = [
        _rec("2026-08-01 10:00"),
        _rec("2026-08-02 10:00", status="error"),
        _rec("2026-08-03 10:00", status="processing"),
    ]
    assert badges.compute_metrics(recs, "roleplay")["count"] == 1


def test_high_score_streak_counts_consecutive_runs():
    """20点以上（平均4.0以上）の連続。間に低い回が入ると切れる。"""
    totals = [20, 21, 25, 14, 20, 20]
    recs = [_rec(f"2026-08-{i+1:02d} 10:00", total=t) for i, t in enumerate(totals)]
    m = badges.compute_metrics(recs, "roleplay")
    assert m["high_streak"] == 3     # 20,21,25
    assert m["high_total"] == 5
    assert m["best_total"] == 25


def test_day_streak_needs_consecutive_calendar_days():
    recs = [_rec(d + " 10:00") for d in
            ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-06")]
    m = badges.compute_metrics(recs, "roleplay")
    assert m["day_streak"] == 3
    assert m["active_days"] == 4


def test_same_day_twice_is_one_active_day():
    recs = [_rec("2026-08-01 10:00"), _rec("2026-08-01 18:00")]
    m = badges.compute_metrics(recs, "roleplay")
    assert m["active_days"] == 1
    assert m["count"] == 2


def test_improve_streak_counts_rising_scores():
    totals = [10, 12, 15, 14, 16, 18, 20]
    recs = [_rec(f"2026-08-{i+1:02d} 10:00", total=t) for i, t in enumerate(totals)]
    assert badges.compute_metrics(recs, "roleplay")["improve_streak"] == 3  # 14→16→18→20


def test_homework_metrics_use_follow_up():
    """『前回の1点をやり切った』は follow_up の done を数える。"""
    recs = [
        _rec("2026-08-01 10:00", follow_up={"status": "done"}),
        _rec("2026-08-02 10:00", follow_up={"status": "not_yet"}),
        _rec("2026-08-03 10:00", follow_up={"status": "done"}),
        _rec("2026-08-04 10:00", follow_up={"status": "done"}),
    ]
    m = badges.compute_metrics(recs, "roleplay")
    assert m["homework_done"] == 3
    assert m["homework_streak"] == 2


def test_meeting_specific_metrics():
    recs = [_rec(
        "2026-08-01 10:00", roleplay=False,
        hidden_needs=[{"inferred_need": "a", "surfaced": True},
                      {"inferred_need": "b", "surfaced": False}],
        johari={"open_pct": 30, "blind_pct": 35, "hidden_pct": 25, "unknown_pct": 10},
        knowledge=[{"category": "product", "point": "x"}],
    )]
    m = badges.compute_metrics(recs, "meeting")
    assert m["hidden_surfaced"] == 1
    assert m["value_zone_best"] == 60      # 盲点35 + 秘密25
    assert m["knowledge_total"] == 1


def test_perfect_criterion_needs_repeats():
    """項目を『極める』は1回の満点では取れない（段階を上る実感のため）。"""
    key = settings.EVALUATION_CRITERIA[0].key
    perfect = {"scores": [{"key": key, "sales_score": 5}]}

    def rec(day):
        return {"saved_at": f"2026-08-{day:02d} 10:00", "status": "done",
                "label": "🎙️1人ロープレ｜導入", "result": perfect}

    one = badges.evaluate([rec(1)])
    three = badges.evaluate([rec(1), rec(2), rec(3)])
    target = f"roleplay_perfect_{key}"
    assert not next(s for s in one if s.badge.id == target).earned
    assert next(s for s in three if s.badge.id == target).earned


def test_no_history_earns_nothing():
    statuses = badges.evaluate([])
    assert badges.earned_count(statuses) == 0
    assert len(statuses) == len(ALL_BADGES)
    assert badges.next_up(statuses) == []      # 0件のときは励ましを出さない


def test_first_roleplay_earns_the_first_step():
    statuses = badges.evaluate([_rec("2026-08-01 10:00", total=10)])
    earned = {s.badge.id for s in statuses if s.earned}
    assert "roleplay_count_1" in earned
    assert "meeting_count_1" not in earned


def test_progress_and_remaining_for_locked_badge():
    recs = [_rec(f"2026-08-{i+1:02d} 10:00") for i in range(3)]
    s = next(x for x in badges.evaluate(recs) if x.badge.id == "roleplay_count_5")
    assert not s.earned
    assert s.current == 3 and s.remaining == 2
    assert 0.59 < s.progress < 0.61


def test_next_up_skips_untouched_badges():
    """まだ0のバッジは『あと少し』に出さない（励ましにならないため）。"""
    recs = [_rec(f"2026-08-{i+1:02d} 10:00", total=21) for i in range(3)]
    nxt = badges.next_up(badges.evaluate(recs), 3)
    assert nxt and all(s.current > 0 for s in nxt)
    assert all(not s.earned for s in nxt)


def test_all_badges_reference_a_real_metric():
    """定義した全バッジの指標が、実際に計算される指標に存在する。"""
    keys = set(badges.compute_metrics([], "roleplay"))
    for b in ALL_BADGES:
        assert b.metric in keys, f"{b.id} の指標 {b.metric} が計算されていない"
