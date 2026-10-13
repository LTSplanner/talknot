"""2つの視点（ナレッジ／目指す営業像）の評価を必須にする仕組みを確かめる。"""
import copy
import json
import types as pytypes

import pytest

from config import settings
from core import lenses, prompts
from core.models import EvaluationResult
from services import gemini_analyzer
from tests.test_models import SAMPLE

LENSES = {
    "knowledge": {
        "verdict": "一部ずれ",
        "points": [{"timestamp": "T2", "said": "同行は無料です",
                    "knowledge": "通常49,500円（税込）。条件を満たすと無料",
                    "comment": "無料になる条件まで伝える"}],
        "comment": "料金の条件が抜けていた",
    },
    "ideal": {
        "steps": [{"name": "受注への前進", "status": "一部", "note": "T3で日程を決めなかった"}],
        "stumble": "内覧会同行の日程を決めずに終えた",
        "root_cause": "費用の不安を先に解かなかった",
        "comment": "次の一歩をその場で決めよう",
    },
}


def _with_lenses():
    data = copy.deepcopy(SAMPLE)
    data["lenses"] = copy.deepcopy(LENSES)
    return data


# --- ナレッジの解決 -------------------------------------------------------- #

def test_resolve_knowledge_uses_sheet_when_present():
    text, status = lenses.resolve_knowledge("シートの知識")
    assert text == "シートの知識"
    assert status == lenses.KNOWLEDGE_FULL


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_resolve_knowledge_falls_back_when_empty(empty):
    text, status = lenses.resolve_knowledge(empty)
    assert status == lenses.KNOWLEDGE_FALLBACK
    assert "49,500円" in text


# --- 必須チェック ---------------------------------------------------------- #

def test_require_lenses_accepts_complete():
    lenses.require_lenses({"lenses": LENSES})


@pytest.mark.parametrize("data", [
    {},
    {"lenses": {}},
    {"lenses": {"knowledge": {"comment": "x"}}},
    {"lenses": {"ideal": {"comment": "x"}}},
    {"lenses": {"knowledge": {"comment": ""}, "ideal": {"comment": "x"}}},
])
def test_require_lenses_rejects_missing(data):
    with pytest.raises(lenses.LensMissingError):
        lenses.require_lenses(data)


# --- プロンプト ------------------------------------------------------------ #

def test_prompt_includes_lenses_only_when_required():
    plain = prompts.build_roleplay_prompt(["こんにちは"])
    assert '"lenses"' not in plain
    required = prompts.build_roleplay_prompt(["こんにちは"], lens_knowledge_status="full")
    assert '"lenses"' in required
    assert "目指す営業像" in required


def test_prompt_mentions_fallback():
    p = prompts.build_roleplay_prompt(["こんにちは"], lens_knowledge_status="fallback")
    assert "控えの知識" in p


# --- 結果の保存と復元 ------------------------------------------------------ #

def test_round_trip_keeps_lenses_and_status():
    data = _with_lenses()
    data["knowledge_status"] = "fallback"
    r = EvaluationResult.from_dict(data)
    assert r.knowledge_status == "fallback"
    assert r.lenses.ideal.root_cause == "費用の不安を先に解かなかった"
    again = EvaluationResult.from_dict(json.loads(json.dumps(r.to_dict(), ensure_ascii=False)))
    assert again.lenses.knowledge.points[0].timestamp == "T2"
    assert again.knowledge_status == "fallback"


def test_old_results_have_no_lenses():
    r = EvaluationResult.from_dict(copy.deepcopy(SAMPLE))
    assert r.lenses is None
    assert r.knowledge_status == ""


# --- 解析の流れ（API はモック） ------------------------------------------- #

class _Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        outer = self

        class _Models:
            def generate_content(self, model, contents, config):
                outer.calls += 1
                return pytypes.SimpleNamespace(text=json.dumps(outer.replies.pop(0)))

        class _Files:
            def delete(self, name):
                pass

        self.models = _Models()
        self.files = _Files()


@pytest.fixture
def genai_with(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test")

    def install(*replies):
        client = _Client(replies)
        monkeypatch.setattr(gemini_analyzer.genai, "Client", lambda api_key: client)
        return client
    return install


def test_roleplay_marks_fallback_when_knowledge_missing(genai_with):
    genai_with(_with_lenses())
    r = gemini_analyzer.analyze_roleplay([b"x"], ["こんにちは"], knowledge_base=None,
                                         require_lenses=True)
    assert r.knowledge_status == "fallback"
    assert r.lenses is not None


def test_roleplay_marks_full_with_knowledge(genai_with):
    genai_with(_with_lenses())
    r = gemini_analyzer.analyze_roleplay([b"x"], ["こんにちは"], knowledge_base="知識",
                                         require_lenses=True)
    assert r.knowledge_status == "full"


def test_roleplay_retries_once_when_lenses_missing(genai_with):
    client = genai_with(copy.deepcopy(SAMPLE), _with_lenses())
    r = gemini_analyzer.analyze_roleplay([b"x"], ["こんにちは"], knowledge_base="知識",
                                         require_lenses=True)
    assert client.calls == 2
    assert r.lenses is not None


def test_roleplay_fails_when_lenses_still_missing(genai_with):
    genai_with(copy.deepcopy(SAMPLE), copy.deepcopy(SAMPLE))
    with pytest.raises(lenses.LensMissingError):
        gemini_analyzer.analyze_roleplay([b"x"], ["こんにちは"], knowledge_base="知識",
                                         require_lenses=True)


def test_roleplay_unchanged_when_not_required(genai_with):
    client = genai_with(copy.deepcopy(SAMPLE))
    r = gemini_analyzer.analyze_roleplay([b"x"], ["こんにちは"], knowledge_base=None)
    assert client.calls == 1
    assert r.knowledge_status == ""
