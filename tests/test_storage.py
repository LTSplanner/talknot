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


def test_reference_accumulates_and_concatenates(tmp_storage):
    assert storage.get_reference_talk() is None
    storage.add_reference_talk("一件目の模範トーク", label="A")
    storage.add_reference_talk("二件目の模範トーク", label="B")
    base = storage.get_reference_talk()
    assert "一件目の模範トーク" in base and "二件目の模範トーク" in base
    assert len(storage.list_reference_talks()) == 2


def test_reference_job_lifecycle_and_get_skips_unfinished(tmp_storage):
    storage.start_reference_job("ref_1", "商談動画")
    # 処理中はプロンプト用テキストに含めない
    assert storage.get_reference_talk() is None
    storage.finish_reference("ref_1", "文字起こし結果のトーク")
    assert "文字起こし結果のトーク" in storage.get_reference_talk()
    # 失敗ジョブも基準には混ぜない
    storage.start_reference_job("ref_2", "壊れた動画")
    storage.fail_reference("ref_2", "上限超過")
    items = {it["id"]: it for it in storage.list_reference_talks()}
    assert items["ref_2"]["status"] == "error"
    assert "文字起こし結果のトーク" in storage.get_reference_talk()


def test_reference_delete_and_clear(tmp_storage):
    storage.add_reference_talk("消す対象", label="X")
    rid = storage.list_reference_talks()[0]["id"]
    storage.delete_reference_talk(rid)
    assert storage.list_reference_talks() == []
    storage.add_reference_talk("また追加")
    storage.clear_reference_talks()
    assert storage.list_reference_talks() == []


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


def test_background_job_lifecycle_done(tmp_storage):
    handle = storage.start_evaluation("taro@x.com", "20260620_1_abc", "商談A")
    recs = storage.list_evaluations("taro@x.com")
    assert recs[0]["status"] == "processing" and recs[0]["result"] is None
    storage.finish_evaluation(handle, "taro@x.com", EvaluationResult.from_dict(SAMPLE), "商談A")
    recs = storage.list_evaluations("taro@x.com")
    assert len(recs) == 1  # 同じレコードを更新（増えない）
    assert recs[0]["status"] == "done"
    assert recs[0]["result"]["summary"] == SAMPLE["summary"]


def test_knowledge_uses_sheets_when_configured(tmp_storage, monkeypatch):
    """シート設定時は、保存/読込がスプレッドシート側へ振り向けられること（ネット非依存・モック）。"""
    from services import sheets_knowledge

    store: dict = {"rows": []}
    monkeypatch.setattr(sheets_knowledge, "configured", lambda: True)
    monkeypatch.setattr(sheets_knowledge, "load", lambda: list(store["rows"]))
    monkeypatch.setattr(
        sheets_knowledge, "save", lambda items: store.__setitem__("rows", list(items))
    )

    added = storage.append_knowledge([KnowledgeItem("rule", "契約前に資金計画を共有")])
    assert added == 1
    assert store["rows"] and store["rows"][0]["point"] == "契約前に資金計画を共有"
    assert "資金計画" in storage.get_knowledge_base()


def test_background_job_lifecycle_error(tmp_storage):
    handle = storage.start_evaluation("hana@x.com", "20260620_2_def", "商談B")
    storage.fail_evaluation(handle, "hana@x.com", "無料枠の上限です", "商談B")
    recs = storage.list_evaluations("hana@x.com")
    assert len(recs) == 1
    assert recs[0]["status"] == "error"
    assert recs[0]["error"] == "無料枠の上限です"
