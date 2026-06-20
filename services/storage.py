"""模範トーク・評価履歴の永続化。

保存先は2系統：
- `settings.GCS_BUCKET` が設定されていれば **Google Cloud Storage**（Cloud Run 等で
  再起動しても消えないようにする本番向け）。
- 未設定ならローカルファイル（`settings.DATA_DIR`。ローカル開発・テスト向け）。

入出力インターフェースをここに集約し、呼び出し側（app.py）は保存先を意識しない。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import settings
from core.models import EvaluationResult, KnowledgeItem

# 模範トークの基準テキストのキー（GCSオブジェクト名 / ローカルファイル名）。
_REFERENCE_TEXT_NAME = "reference.txt"

# 弊社ナレッジ（蓄積知識）の保存名と上限。
_KNOWLEDGE_NAME = "knowledge.json"
# 知識項目の上限。超えたら古いものから間引き、毎回の評価コストと容量を一定に保つ。
_KNOWLEDGE_MAX_ITEMS = 150


# --------------------------------------------------------------------------- #
# バックエンド判定
# --------------------------------------------------------------------------- #
def _use_gcs() -> bool:
    return bool(settings.GCS_BUCKET)


def _bucket():
    """GCS バケットを返す（google-cloud-storage は遅延 import）。"""
    from google.cloud import storage  # type: ignore

    client = storage.Client()
    return client.bucket(settings.GCS_BUCKET)


def _gcs_path(*parts: str) -> str:
    return "/".join([settings.GCS_PREFIX, *parts]).strip("/")


# --------------------------------------------------------------------------- #
# ローカル用ヘルパ
# --------------------------------------------------------------------------- #
def _reference_text_path() -> Path:
    # settings の値を実行時に参照（テストで差し替え可能にするため）
    return settings.REFERENCE_TALKS_DIR / _REFERENCE_TEXT_NAME


def _ensure_dirs() -> None:
    settings.REFERENCE_TALKS_DIR.mkdir(parents=True, exist_ok=True)
    settings.EVALUATIONS_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# 模範トーク
# --------------------------------------------------------------------------- #
def save_reference_talk(content: bytes | str, filename: str | None = None) -> str:
    """模範トークを保存する。

    テキストは基準テキストとして、動画/ファイルは原本として保存する。
    保存先のパス（ローカルパス or GCS オブジェクト名）を文字列で返す。
    """
    if _use_gcs():
        bucket = _bucket()
        if isinstance(content, str):
            name = _gcs_path("reference_talks", _REFERENCE_TEXT_NAME)
            bucket.blob(name).upload_from_string(content, content_type="text/plain")
            return name
        name = _gcs_path("reference_talks", filename or "reference_upload")
        bucket.blob(name).upload_from_string(content)
        return name

    _ensure_dirs()
    if isinstance(content, str):
        path = _reference_text_path()
        path.write_text(content, encoding="utf-8")
        return str(path)
    target = settings.REFERENCE_TALKS_DIR / (filename or "reference_upload")
    target.write_bytes(content)
    return str(target)


def get_reference_talk() -> str | None:
    """評価時にプロンプトへ渡す基準テキストを返す（無ければ None）。"""
    if _use_gcs():
        blob = _bucket().blob(_gcs_path("reference_talks", _REFERENCE_TEXT_NAME))
        if blob.exists():
            return blob.download_as_text()
        return None

    path = _reference_text_path()
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# --------------------------------------------------------------------------- #
# 弊社ナレッジ（過去商談から蓄積する社内知識）
# --------------------------------------------------------------------------- #
_CATEGORY_LABELS = {
    "product": "商品知識",
    "rule": "社内ルール",
    "technique": "トーク技術",
}


def _knowledge_path() -> Path:
    return settings.DATA_DIR / _KNOWLEDGE_NAME


def _load_knowledge() -> list[dict]:
    if _use_gcs():
        blob = _bucket().blob(_gcs_path(_KNOWLEDGE_NAME))
        if not blob.exists():
            return []
        try:
            return json.loads(blob.download_as_text())
        except (json.JSONDecodeError, OSError):
            return []
    path = _knowledge_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_knowledge(items: list[dict]) -> None:
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    if _use_gcs():
        _bucket().blob(_gcs_path(_KNOWLEDGE_NAME)).upload_from_string(
            payload, content_type="application/json"
        )
        return
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _knowledge_path().write_text(payload, encoding="utf-8")


def append_knowledge(items: list[KnowledgeItem]) -> int:
    """抽出した知識を蓄積する。重複は除外し、上限を超えたら古いものから間引く。

    追加された新規件数を返す。
    """
    if not items:
        return 0
    existing = _load_knowledge()
    seen = {(_norm(e.get("point", ""))) for e in existing}
    added = 0
    for it in items:
        point = (it.point or "").strip()
        if not point or _norm(point) in seen:
            continue
        existing.append({"category": it.category, "point": point})
        seen.add(_norm(point))
        added += 1
    if added:
        # 上限超過分は古い方（先頭）から落とす
        existing = existing[-_KNOWLEDGE_MAX_ITEMS:]
        _save_knowledge(existing)
    return added


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def get_knowledge_items() -> list[dict]:
    """蓄積された知識を返す（カテゴリ・内容の dict のリスト）。"""
    return _load_knowledge()


def get_knowledge_base() -> str | None:
    """評価プロンプトへ渡す『弊社ナレッジ』テキストを返す（無ければ None）。"""
    items = _load_knowledge()
    if not items:
        return None
    lines = []
    for cat in ("product", "rule", "technique"):
        group = [i["point"] for i in items if i.get("category") == cat]
        if not group:
            continue
        lines.append(f"【{_CATEGORY_LABELS[cat]}】")
        lines.extend(f"- {p}" for p in group)
    # カテゴリ未分類のものも拾う
    other = [i["point"] for i in items if i.get("category") not in _CATEGORY_LABELS]
    if other:
        lines.append("【その他】")
        lines.extend(f"- {p}" for p in other)
    return "\n".join(lines)


def clear_knowledge() -> None:
    """蓄積した知識をすべて消す（管理者操作）。"""
    _save_knowledge([])


# --------------------------------------------------------------------------- #
# 評価履歴
# --------------------------------------------------------------------------- #
def _safe(user_email: str) -> str:
    return user_email.replace("@", "_at_").replace("/", "_")


def save_evaluation(user_email: str, result: EvaluationResult, label: str = "") -> str:
    record = {
        "user_email": user_email,
        "label": label,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "result": result.to_dict(),
    }
    payload = json.dumps(record, ensure_ascii=False, indent=2)
    fname = f"{_safe(user_email)}_{time.strftime('%Y%m%d_%H%M%S')}.json"

    if _use_gcs():
        name = _gcs_path("evaluations", fname)
        _bucket().blob(name).upload_from_string(
            payload, content_type="application/json"
        )
        return name

    _ensure_dirs()
    path = settings.EVALUATIONS_DIR / fname
    path.write_text(payload, encoding="utf-8")
    return str(path)


def list_evaluations(user_email: str) -> list[dict]:
    """指定ユーザーの評価履歴を新しい順で返す。"""
    prefix_name = _safe(user_email)

    if _use_gcs():
        bucket = _bucket()
        blobs = list(
            bucket.list_blobs(prefix=_gcs_path("evaluations", prefix_name))
        )
        records = []
        for blob in sorted(blobs, key=lambda b: b.name, reverse=True):
            try:
                records.append(json.loads(blob.download_as_text()))
            except (json.JSONDecodeError, OSError):
                continue
        return records

    if not settings.EVALUATIONS_DIR.exists():
        return []
    records = []
    for path in sorted(
        settings.EVALUATIONS_DIR.glob(f"{prefix_name}_*.json"), reverse=True
    ):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records
