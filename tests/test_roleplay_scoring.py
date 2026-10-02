"""ロープレの採点とフィードバックが、練習の意欲を削がないことのテスト。

実際に出た声：
- 「0点が出る。最低1点にしてと伝えたはず」「普通にやって2点はありえない」（2026-09-16）
- 「カンペ通りに言っても『こう言えたら』と直される」
- 「『はい』『そうですね』などの相槌にフィードバックが付く」（2026-09-20）
"""
import pytest

from core import prompts
from core.models import EvaluationResult, clamp_score, is_filler


class TestScoreNeverDropsToZero:
    @pytest.mark.parametrize("raw,want", [(0, 1), (-3, 1), (1, 1), (3, 3), (5, 5), (9, 5)])
    def test_scores_are_kept_between_one_and_five(self, raw, want):
        assert clamp_score(raw) == want

    @pytest.mark.parametrize("raw", [None, "", "さん", [], {}])
    def test_broken_values_become_the_minimum(self, raw):
        assert clamp_score(raw) == 1

    def test_a_zero_from_the_ai_is_shown_as_one(self):
        """0点は『評価不能』であって『最低評価』ではない。"""
        r = EvaluationResult.from_dict(
            {"scores": [{"key": "emotion_catch", "sales_score": 0, "reference_score": 0}]})
        assert r.scores[0].sales_score == 1
        assert r.scores[0].reference_score == 1

    def test_total_cannot_be_absurdly_low(self):
        """5項目すべて0でも 5/25 になる（0/25 や 2/25 は出さない）。"""
        r = EvaluationResult.from_dict(
            {"scores": [{"key": k, "sales_score": 0} for k in
                        ("emotion_catch", "background_depth", "excitement",
                         "adaptability", "additional_consideration")]})
        assert r.total == 5


class TestFillerWordsAreNotCoached:
    @pytest.mark.parametrize("text", [
        "はい", "ええ", "そうですね。", "なるほど", "確かに", "ありがとうございます。",
        "分かりました", "はい、そうですね", "なるほど、はい。", "", "　",
    ])
    def test_a_simple_response_is_recognised_as_filler(self, text):
        assert is_filler(text)

    @pytest.mark.parametrize("text", [
        "はい、玄関やトイレで消し忘れはありませんか？",
        "コーティングは入居前だと家具の移動が要りません。",
        "そうですね、まずはLDKから考えてみませんか。",
    ])
    def test_real_talk_is_not_filler(self, text):
        assert not is_filler(text)

    def test_feedback_on_a_filler_is_dropped(self):
        """相槌の言い換えを指摘しても、話し方の練習にならない。"""
        r = EvaluationResult.from_dict({"feedback": [
            {"timestamp": "T1", "before": "はい。", "after": "こう言えたら…"},
            {"timestamp": "T2", "before": "コーティングは3種類ございます。",
             "after": "お住まいに合わせて3種類からお選びいただけます。"},
        ]})
        assert len(r.feedback) == 1
        assert r.feedback[0].timestamp == "T2"

    def test_feedback_without_a_before_is_kept(self):
        """before を特定できなかった指摘は残す（相槌とは別の話）。"""
        r = EvaluationResult.from_dict(
            {"feedback": [{"timestamp": "T1", "before": "", "after": "こう言えたら…"}]})
        assert len(r.feedback) == 1


class TestThePromptGradesAgainstTheScript:
    def _prompt(self, hints=None):
        return prompts.build_roleplay_prompt(
            ["高いですね…", "考えます"], talk_script="（模範トーク）",
            scenario_hints=hints)

    def test_the_hints_shown_to_the_planner_are_given_to_the_ai(self):
        """カンペを渡さないと、AIは何を言うべきだったか知らないまま採点してしまう。"""
        p = self._prompt(["【STEP1】まず受け止める。モデル：『そうですよね』", ""])
        assert "お手本" in p
        assert "まず受け止める" in p

    def test_following_the_script_must_not_be_penalised(self):
        assert "どおりに言えていれば" in self._prompt(["お手本"])

    def test_missing_scenes_are_scored_as_standard(self):
        assert "出番が無かった観点は 3" in self._prompt()

    def test_zero_is_forbidden_in_the_prompt_too(self):
        assert "0 点は付けない" in self._prompt()

    def test_the_ai_is_told_to_skip_filler(self):
        p = self._prompt()
        assert "相槌・返事だけの発話は対象にしない" in p
        assert "なるほど" in p

    def test_no_hints_still_builds_a_valid_prompt(self):
        p = self._prompt(None)
        assert "お手本（練習者に表示していたカンペ）" not in p
        assert "1人ロープレ" in p
