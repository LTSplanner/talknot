"""失敗した評価をやり直す処理のテスト。

「ロープレはやったのに評価が失敗して、やっていないことにされる」のを無くすための
仕組みなので、拾うべきものを拾い、拾ってはいけないものを拾わないことを守る。
"""
import datetime as dt
import importlib.util
import json
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "retry_failed_evaluations",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "retry_failed_evaluations.py",
)
retry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(retry)


def _payload(attempts=0, files=1):
    return json.dumps({
        "kind": "roleplay",
        "audio_files": [{"uri": f"files/abc{i}", "mime": "audio/wav"} for i in range(files)],
        "scenario_lines": ["お客様のセリフ"],
        "focus": None, "planner_name": "安栗", "attempts": attempts,
    }, ensure_ascii=False)


def _rec(status="error", hours_ago=2, payload=None, **kw):
    saved = (dt.datetime.now() - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
    rec = {"job_id": "j1", "user_email": "manguri@life-time-support.com",
           "saved_at": saved, "status": status, "label": "🎙️1人ロープレ｜信頼構築",
           "error": "high demand", "retry_payload": payload if payload is not None else _payload()}
    rec.update(kw)
    return rec


class TestWhatGetsRetried:
    def test_a_failed_roleplay_with_audio_is_retried(self):
        assert len(retry.find_targets([_rec()])) == 1

    def test_a_finished_evaluation_is_left_alone(self):
        assert retry.find_targets([_rec(status="done")]) == []

    def test_a_failure_without_audio_cannot_be_retried(self):
        """材料が無いものは拾わない（拾っても評価できない）。"""
        assert retry.find_targets([_rec(payload="")]) == []
        assert retry.find_targets([_rec(payload="こわれている")]) == []

    def test_a_job_still_running_is_not_stolen(self):
        """アプリ側でまだ走っている可能性があるので、処理中は1時間待つ。"""
        assert retry.find_targets([_rec(status="processing", hours_ago=0.2)]) == []
        assert len(retry.find_targets([_rec(status="processing", hours_ago=3)])) == 1

    def test_it_gives_up_after_enough_attempts(self):
        """延々とやり直して無料枠を使い切らない。"""
        assert retry.find_targets([_rec(payload=_payload(attempts=retry.MAX_ATTEMPTS))]) == []
        assert len(retry.find_targets([_rec(payload=_payload(attempts=1))])) == 1

    def test_expired_audio_is_not_retried(self):
        """預けた録音は48時間で消えるので、それ以降は対象外。"""
        assert retry.find_targets([_rec(hours_ago=retry.PAYLOAD_TTL_HOURS + 2)]) == []

    def test_oldest_first(self):
        old = _rec(hours_ago=20)
        new = _rec(hours_ago=2)
        assert retry.find_targets([new, old])[0] is old


class TestItDoesNotMakeCongestionWorse:
    def test_it_processes_only_a_few_per_run(self):
        assert 1 <= retry.MAX_PER_RUN <= 5

    def test_it_waits_between_jobs(self):
        assert retry.GAP_SEC >= 20

    def test_each_retry_asks_for_less_thinking(self):
        """混雑時は軽いリクエストの方が通る。回を追うごとに軽くする。"""
        ladder = retry.THINKING_LADDER
        assert ladder == sorted(ladder, reverse=True)
        assert len(ladder) >= retry.MAX_ATTEMPTS


class TestAgeCalculation:
    def test_broken_timestamp_is_treated_as_new(self):
        assert retry._age_hours("こわれた日付") == 0.0

    @pytest.mark.parametrize("hours", [0.5, 5, 50])
    def test_age_is_measured_in_hours(self, hours):
        saved = (dt.datetime.now() - dt.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        assert abs(retry._age_hours(saved) - hours) < 0.1
