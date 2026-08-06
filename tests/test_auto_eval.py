"""core.auto_eval の純ロジックのテスト（初回判定・対象選定・重複/古い順/上限）。"""
from core import auto_eval


# --------------------------------------------------------------------------- #
# is_first_meeting
# --------------------------------------------------------------------------- #
class TestIsFirstMeeting:
    def test_true_for_first_meeting(self):
        assert auto_eval.is_first_meeting("初回商談 L260721484101 田中様")

    def test_true_when_keyword_anywhere(self):
        assert auto_eval.is_first_meeting("L260721 【初回】オンライン")

    def test_false_for_second_meeting(self):
        assert not auto_eval.is_first_meeting("2回目以降の商談 L260721484101")

    def test_false_without_keyword(self):
        assert not auto_eval.is_first_meeting("商談 L260721484101")

    def test_empty_is_false(self):
        assert not auto_eval.is_first_meeting("")
        assert not auto_eval.is_first_meeting(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# case_ids_in
# --------------------------------------------------------------------------- #
class TestCaseIdsIn:
    def test_extracts_case_id(self):
        assert auto_eval.case_ids_in("初回商談 L260721484101 田中様") == {"L260721484101"}

    def test_strips_spaces_in_id(self):
        assert auto_eval.case_ids_in("初回商談 L 260721484101") == {"L260721484101"}

    def test_none_when_no_id(self):
        assert auto_eval.case_ids_in("商談メモ") == set()

    def test_empty_text(self):
        assert auto_eval.case_ids_in("") == set()


# --------------------------------------------------------------------------- #
# select_targets
# --------------------------------------------------------------------------- #
def _cand(planner, case_id, start, summary="初回商談"):
    return {
        "planner": planner,
        "case_id": case_id,
        "summary": f"{summary} {case_id}",
        "start": start,
        "start_date": start[:10],
    }


class TestSelectTargets:
    def test_excludes_done_case_ids(self):
        cands = [
            _cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00"),
            _cand("b@x.com", "L200000", "2026-07-02T10:00:00+09:00"),
        ]
        out = auto_eval.select_targets(cands, {"L100000"}, 5)
        assert [c["case_id"] for c in out] == ["L200000"]

    def test_sorts_oldest_first(self):
        cands = [
            _cand("a@x.com", "L300000", "2026-07-03T10:00:00+09:00"),
            _cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00"),
            _cand("a@x.com", "L200000", "2026-07-02T10:00:00+09:00"),
        ]
        out = auto_eval.select_targets(cands, set(), 5)
        assert [c["case_id"] for c in out] == ["L100000", "L200000", "L300000"]

    def test_respects_limit(self):
        cands = [
            _cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00"),
            _cand("a@x.com", "L200000", "2026-07-02T10:00:00+09:00"),
            _cand("a@x.com", "L300000", "2026-07-03T10:00:00+09:00"),
        ]
        out = auto_eval.select_targets(cands, set(), 2)
        assert [c["case_id"] for c in out] == ["L100000", "L200000"]

    def test_limit_zero_or_negative_returns_empty(self):
        cands = [_cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00")]
        assert auto_eval.select_targets(cands, set(), 0) == []
        assert auto_eval.select_targets(cands, set(), -1) == []

    def test_excludes_empty_case_id(self):
        cands = [
            _cand("a@x.com", "", "2026-07-01T10:00:00+09:00"),
            _cand("b@x.com", "L200000", "2026-07-02T10:00:00+09:00"),
        ]
        out = auto_eval.select_targets(cands, set(), 5)
        assert [c["case_id"] for c in out] == ["L200000"]

    def test_dedupes_case_id_keeping_oldest(self):
        # 同じ案件が複数回（別プランナー枠等）現れても、最も古い1件だけ残す。
        cands = [
            _cand("a@x.com", "L100000", "2026-07-05T10:00:00+09:00"),
            _cand("b@x.com", "L100000", "2026-07-01T10:00:00+09:00"),
        ]
        out = auto_eval.select_targets(cands, set(), 5)
        assert len(out) == 1
        assert out[0]["case_id"] == "L100000"
        assert out[0]["planner"] == "b@x.com"  # 古い方を残す

    def test_done_ids_normalized(self):
        # done 側に空白入りの案件番号が来ても正規化して一致させる。
        cands = [_cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00")]
        assert auto_eval.select_targets(cands, {"L 100000"}, 5) == []

    def test_falls_back_to_start_date_when_no_start(self):
        c1 = {"planner": "a@x.com", "case_id": "L200000",
              "summary": "初回商談", "start": "", "start_date": "2026-07-02"}
        c2 = {"planner": "a@x.com", "case_id": "L100000",
              "summary": "初回商談", "start": "", "start_date": "2026-07-01"}
        out = auto_eval.select_targets([c1, c2], set(), 5)
        assert [c["case_id"] for c in out] == ["L100000", "L200000"]

    def test_does_not_mutate_input(self):
        cands = [
            _cand("a@x.com", "L300000", "2026-07-03T10:00:00+09:00"),
            _cand("a@x.com", "L100000", "2026-07-01T10:00:00+09:00"),
        ]
        before = [c["case_id"] for c in cands]
        auto_eval.select_targets(cands, set(), 5)
        assert [c["case_id"] for c in cands] == before

    def test_empty_candidates(self):
        assert auto_eval.select_targets([], set(), 5) == []


def test_spec_meetings_are_excluded():
    """「初回仕様MT」は初回だが商談ではないので自動評価しない。"""
    assert not auto_eval.is_first_meeting("初回仕様MT オンライン L260707478901　安宮綾水様｜バウス加賀324号室")
    assert not auto_eval.is_first_meeting("初回仕様MT SR L260615468701　山崎光様")
    assert not auto_eval.is_first_meeting("仕様打ち合わせ L260615468701　山崎光様")


def test_real_first_meetings_are_still_targeted():
    """オンラインの初回商談はこれまでどおり対象のまま。"""
    assert auto_eval.is_first_meeting("◎初回商談 オンライン L260726486501　矢野淳也様｜江戸川区新築マンション")
    assert auto_eval.is_first_meeting("○初回商談 オンライン L260729487401　西依尚士様｜ザグランクロス多摩センター")


class TestDoneCaseIds:
    """再評価の対象から外す案件の判定。"""

    def _rec(self, case_id, status="done"):
        return {"label": f"◎初回商談 {case_id}　佐藤様", "status": status}

    def test_success_is_treated_as_finished(self):
        assert auto_eval.done_case_ids([self._rec("L260722484601")]) == {"L260722484601"}

    def test_a_failure_is_retried(self):
        """無料枠の枠切れ(429)で落ちた商談を、翌日また拾えるようにする。"""
        assert auto_eval.done_case_ids([self._rec("L260722484601", "error")]) == set()

    def test_repeated_failures_are_given_up(self):
        """毎日同じ商談で失敗し続けるのを避ける（内容の問題とみなす）。"""
        recs = [self._rec("L260722484601", "error")] * auto_eval.MAX_RETRY_ON_ERROR
        assert auto_eval.done_case_ids(recs) == {"L260722484601"}

    def test_processing_is_not_started_twice(self):
        assert auto_eval.done_case_ids(
            [self._rec("L260722484601", "processing")]) == {"L260722484601"}

    def test_success_after_failures_stays_finished(self):
        recs = [self._rec("L1234567", "error"), self._rec("L1234567", "done")]
        assert auto_eval.done_case_ids(recs) == {"L1234567"}


def test_showroom_meetings_are_excluded():
    """SR（ショールーム）の対面商談は自動評価しない。"""
    assert not auto_eval.is_first_meeting("◎初回商談 SR L260722484801　周鈺庭様｜MID FRONT")
    assert not auto_eval.is_first_meeting("初回商談 SR L260722484601　福島慶紀様")


def test_sr_inside_another_word_does_not_exclude():
    """「SRC造」のように他の語の一部と一致したときは除外しない。"""
    assert auto_eval.is_first_meeting("◎初回商談 オンライン L260722484801　SRC造の物件")


def test_online_meetings_are_still_targeted():
    assert auto_eval.is_first_meeting(
        "◎初回商談 オンライン L260718483201　篠崎颯将様｜クレストフォルム横浜踊場")
