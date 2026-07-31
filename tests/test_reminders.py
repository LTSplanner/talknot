"""core.reminders の純ロジックのテスト（当日判定・対象者フィルタ・JST境界）。"""
import datetime as _dt

import pytest

from core import reminders


def _rec(email, saved_at, label="🎙️ ロープレ／導入"):
    return {"user_email": email, "saved_at": saved_at, "label": label}


# --------------------------------------------------------------------------- #
# did_roleplay_today
# --------------------------------------------------------------------------- #
class TestDidRoleplayToday:
    def test_true_when_roleplay_saved_today(self):
        recs = [_rec("a@x.com", "2026-07-27 10:15:03")]
        assert reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")

    def test_false_when_only_yesterday(self):
        recs = [_rec("a@x.com", "2026-07-26 23:59:59")]
        assert not reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")

    def test_ignores_non_roleplay_labels(self):
        # "🎙️" 始まりでない（商談評価など）は当日でも実施扱いにしない。
        recs = [_rec("a@x.com", "2026-07-27 09:00:00", label="📊 商談評価 L2607")]
        assert not reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")

    def test_email_case_and_space_insensitive(self):
        recs = [_rec("A@X.com", "2026-07-27 10:00:00")]
        assert reminders.did_roleplay_today(recs, "  a@x.com ", "2026-07-27")

    def test_other_users_do_not_count(self):
        recs = [_rec("b@x.com", "2026-07-27 10:00:00")]
        assert not reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")

    def test_empty_email_is_false(self):
        recs = [_rec("a@x.com", "2026-07-27 10:00:00")]
        assert not reminders.did_roleplay_today(recs, "", "2026-07-27")

    def test_missing_fields_do_not_crash(self):
        recs = [{}, {"user_email": "a@x.com"}, {"saved_at": "2026-07-27 10:00"}]
        assert not reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")

    def test_label_with_leading_space_still_matches(self):
        recs = [_rec("a@x.com", "2026-07-27 10:00:00", label="  🎙️ ロープレ")]
        assert reminders.did_roleplay_today(recs, "a@x.com", "2026-07-27")


# --------------------------------------------------------------------------- #
# missed_today
# --------------------------------------------------------------------------- #
class TestMissedToday:
    def test_returns_only_users_without_today_roleplay(self):
        recs = [
            _rec("done@x.com", "2026-07-27 11:00:00"),
            _rec("old@x.com", "2026-07-26 11:00:00"),
        ]
        targets = ["done@x.com", "old@x.com", "never@x.com"]
        missed = reminders.missed_today(recs, targets, "2026-07-27")
        assert missed == ["old@x.com", "never@x.com"]

    def test_preserves_target_order(self):
        recs = []
        targets = ["c@x.com", "a@x.com", "b@x.com"]
        assert reminders.missed_today(recs, targets, "2026-07-27") == targets

    def test_dedupes_targets(self):
        recs = []
        targets = ["a@x.com", "A@x.com", "b@x.com"]
        assert reminders.missed_today(recs, targets, "2026-07-27") == ["a@x.com", "b@x.com"]

    def test_empty_targets(self):
        assert reminders.missed_today([], [], "2026-07-27") == []

    def test_all_done_returns_empty(self):
        recs = [_rec("a@x.com", "2026-07-27 10:00:00")]
        assert reminders.missed_today(recs, ["a@x.com"], "2026-07-27") == []


# --------------------------------------------------------------------------- #
# missed_before（午前中の締切判定）
# --------------------------------------------------------------------------- #
class TestMissedBefore:
    def test_roleplay_before_noon_counts_as_done(self):
        recs = [_rec("a@x.com", "2026-07-27 11:59:59")]
        assert reminders.missed_before(
            recs, ["a@x.com"], "2026-07-27", "12:00:00"
        ) == []

    def test_roleplay_at_noon_is_too_late(self):
        recs = [_rec("a@x.com", "2026-07-27 12:00:00")]
        assert reminders.missed_before(
            recs, ["a@x.com"], "2026-07-27", "12:00:00"
        ) == ["a@x.com"]

    def test_afternoon_roleplay_does_not_count_for_morning(self):
        recs = [_rec("a@x.com", "2026-07-27 15:00:00")]
        assert reminders.missed_before(
            recs, ["a@x.com"], "2026-07-27", "12:00:00"
        ) == ["a@x.com"]

    def test_non_roleplay_before_noon_does_not_count(self):
        recs = [_rec(
            "a@x.com", "2026-07-27 10:00:00", label="📊 商談評価 L2607"
        )]
        assert reminders.missed_before(
            recs, ["a@x.com"], "2026-07-27", "12:00:00"
        ) == ["a@x.com"]


# --------------------------------------------------------------------------- #
# is_off_today（休みスキップ判定：タイトル語・終日/時間指定を問わない）
# --------------------------------------------------------------------------- #
def _ev(title, all_day=False):
    return {"title": title, "all_day": all_day}


class TestIsOffToday:
    def test_timed_off_event_is_off(self):
        # 時間指定の「中谷OFF 09:00〜22:00」→ 休み（スキップ）。
        assert reminders.is_off_today([_ev("中谷OFF 09:00〜22:00")])

    def test_timed_halfday_is_not_off(self):
        # 時間指定の「午前休 09:00〜13:00」→ 半休なので送る。
        assert not reminders.is_off_today([_ev("午前休 09:00〜13:00")])

    def test_all_day_paid_leave_is_off(self):
        assert reminders.is_off_today([_ev("有給休暇", all_day=True)])

    def test_summer_holiday_is_off(self):
        # 会社休（夏季休暇）は終日/時間指定を問わず休み。
        assert reminders.is_off_today([_ev("夏季休暇 09:00〜18:00")])
        assert reminders.is_off_today([_ev("夏季休暇", all_day=True)])

    def test_office_day_is_not_off(self):
        # 「事務DAY」はOFF語でないので送る。
        assert not reminders.is_off_today([_ev("事務DAY 09:00〜22:00")])

    def test_private_step_out_is_not_off(self):
        # 「私用中抜け」はOFF語でない（部分中抜けは稼働扱い）ので送る。
        assert not reminders.is_off_today([_ev("私用中抜け 14:00〜15:00")])

    def test_no_off_keyword_is_not_off(self):
        assert not reminders.is_off_today([_ev("MTG"), _ev("資料作成")])

    def test_case_insensitive_off(self):
        assert reminders.is_off_today([_ev("Off")])
        assert reminders.is_off_today([_ev("安栗off 09:00〜18:00")])

    def test_halfday_overrides_even_with_off_word(self):
        # 半休語を含めば、OFF語があっても休みにカウントしない（送る）。
        assert not reminders.is_off_today([_ev("午後休（有給）")])

    def test_off_wins_when_separate_events(self):
        # 半休イベントと別に終日OFFがあれば休み（スキップ）。
        assert reminders.is_off_today([_ev("午前休 09:00〜12:00"), _ev("有給 13:00〜18:00")])

    def test_empty_events_is_not_off(self):
        assert not reminders.is_off_today([])


# --------------------------------------------------------------------------- #
# is_off_morning（正午通知で午前休を除外）
# --------------------------------------------------------------------------- #
class TestIsOffMorning:
    def test_morning_leave_is_off(self):
        assert reminders.is_off_morning([_ev("午前休 09:00〜13:00")])
        assert reminders.is_off_morning([_ev("AM半休")])

    def test_afternoon_leave_is_not_off(self):
        assert not reminders.is_off_morning([_ev("午後休（有給）")])
        assert not reminders.is_off_morning([_ev("PM半休")])

    def test_full_day_leave_is_off(self):
        assert reminders.is_off_morning([_ev("有給休暇", all_day=True)])

    def test_generic_halfday_remains_send_target(self):
        assert not reminders.is_off_morning([_ev("半休")])


# --------------------------------------------------------------------------- #
# today_jst_str（JST境界の簡易確認）
# --------------------------------------------------------------------------- #
class TestTodayJstStr:
    def test_utc_late_night_is_next_day_in_jst(self):
        # 2026-07-27 23:30 UTC は JST では 2026-07-28 08:30。
        utc = _dt.datetime(2026, 7, 27, 23, 30, tzinfo=_dt.timezone.utc)
        assert reminders.today_jst_str(utc) == "2026-07-28"

    def test_utc_afternoon_same_day_in_jst(self):
        utc = _dt.datetime(2026, 7, 27, 3, 0, tzinfo=_dt.timezone.utc)
        assert reminders.today_jst_str(utc) == "2026-07-27"

    def test_naive_datetime_treated_as_jst(self):
        naive = _dt.datetime(2026, 7, 27, 15, 0)
        assert reminders.today_jst_str(naive) == "2026-07-27"

    def test_no_arg_returns_iso_date_string(self):
        out = reminders.today_jst_str()
        # 形式 YYYY-MM-DD であることだけ確認（実日付には依存しない）。
        _dt.date.fromisoformat(out)
        assert len(out) == 10
