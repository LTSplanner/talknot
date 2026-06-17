"""Gemini 解析のパイプラインを、API をモックして検証する（ネットワーク不要）。"""
import json
import types as pytypes

import pytest

from config import settings
from services import gemini_analyzer
from tests.test_models import SAMPLE


class _State:
    def __init__(self, name):
        self.name = name


class _File:
    def __init__(self, name="files/abc", state="ACTIVE"):
        self.name = name
        self.state = _State(state)


class _FakeClient:
    """generate_content に渡された contents を記録する最小モック。"""

    def __init__(self):
        self.captured = {}
        outer = self

        class _Files:
            def upload(self, file):
                outer.captured["uploaded"] = file
                return _File()

            def get(self, name):
                return _File()

            def delete(self, name):
                outer.captured["deleted"] = name

        class _Models:
            def generate_content(self, model, contents, config):
                outer.captured["model"] = model
                outer.captured["contents"] = contents
                return pytypes.SimpleNamespace(text=json.dumps(SAMPLE))

        self.files = _Files()
        self.models = _Models()


@pytest.fixture
def fake_genai(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test")
    client = _FakeClient()
    monkeypatch.setattr(gemini_analyzer.genai, "Client", lambda api_key: client)
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"\x00fake")
    return client, str(video)


def test_analyze_returns_parsed_result(fake_genai):
    client, video = fake_genai
    result = gemini_analyzer.analyze(video, reference_talk="模範")
    assert result.total == 9
    assert result.feedback[0].timestamp == "03:12"


def test_analyze_uploads_and_uses_configured_model(fake_genai):
    client, video = fake_genai
    gemini_analyzer.analyze(video)
    assert client.captured["uploaded"] == video
    assert client.captured["model"] == "gemini-test"
    # プロンプトと動画の両方が contents に渡されている
    assert any(isinstance(c, str) and "MM:SS" in c for c in client.captured["contents"])


def test_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gemini_analyzer.analyze(str(tmp_path / "x.mp4"))
