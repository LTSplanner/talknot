"""模範トーク・評価履歴の永続化テスト（tmp ディレクトリに隔離）。"""
from pathlib import Path

import pytest

from config import settings
from core.models import EvaluationResult, KnowledgeItem
from services import storage
from tests.test_models import SAMPLE


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    ref = tmp_path / "reference_talks"
    ev = tmp_path / "evaluations"
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
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


def test_knowledge_append_dedupe_and_base(tmp_storage):
    assert storage.get_knowledge_base() is None
    added = storage.append_knowledge(
        [
            KnowledgeItem("product", "ZEH仕様は補助金の対象になりやすい"),
            KnowledgeItem("technique", "沈黙の後は要望を一度言語化して返す"),
        ]
    )
    assert added == 2
    # 同じ内容（空白違い）は重複として弾く
    added2 = storage.append_knowledge(
        [KnowledgeItem("product", "ZEH仕様は補助金の対象になりやすい ")]
    )
    assert added2 == 0
    base = storage.get_knowledge_base()
    assert "商品知識" in base and "ZEH仕様" in base
    assert "トーク技術" in base


def test_knowledge_capped(tmp_storage, monkeypatch):
    monkeypatch.setattr(storage, "_KNOWLEDGE_MAX_ITEMS", 3)
    storage.append_knowledge([KnowledgeItem("rule", f"ルール{i}") for i in range(10)])
    items = storage.get_knowledge_items()
    assert len(items) == 3
    # 古いものから間引かれ、新しい3件が残る
    assert items[-1]["point"] == "ルール9"


def test_knowledge_clear(tmp_storage):
    storage.append_knowledge([KnowledgeItem("rule", "テスト")])
    storage.clear_knowledge()
    assert storage.get_knowledge_items() == []
