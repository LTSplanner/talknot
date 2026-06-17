"""模範トーク・評価履歴の永続化テスト（tmp ディレクトリに隔離）。"""
from pathlib import Path

import pytest

from config import settings
from core.models import EvaluationResult
from services import storage
from tests.test_models import SAMPLE


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    ref = tmp_path / "reference_talks"
    ev = tmp_path / "evaluations"
    monkeypatch.setattr(settings, "REFERENCE_TALKS_DIR", ref)
    monkeypatch.setattr(settings, "EVALUATIONS_DIR", ev)
    # テストは常にローカルバックエンドを使う（GCS には触れない）。
    monkeypatch.setattr(settings, "GCS_BUCKET", "")
    return tmp_path


def test_reference_text_roundtrip(tmp_storage):
    assert storage.get_reference_talk() is None
    storage.save_reference_talk("模範トークの基準テキスト")
    assert storage.get_reference_talk() == "模範トークの基準テキスト"


def test_reference_binary_saved(tmp_storage):
    path = Path(storage.save_reference_talk(b"\x00\x01video", "ref.mp4"))
    assert path.exists()
    assert path.read_bytes() == b"\x00\x01video"


def test_evaluation_saved_and_listed(tmp_storage):
    result = EvaluationResult.from_dict(SAMPLE)
    storage.save_evaluation("taro@life-time-support.com", result, "商談A")
    records = storage.list_evaluations("taro@life-time-support.com")
    assert len(records) == 1
    assert records[0]["label"] == "商談A"
    assert records[0]["result"]["summary"] == SAMPLE["summary"]


def test_evaluations_isolated_per_user(tmp_storage):
    storage.save_evaluation("a@x.com", EvaluationResult.from_dict(SAMPLE))
    assert storage.list_evaluations("b@x.com") == []
