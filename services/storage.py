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
from core.models import EvaluationResult

# 模範トークの基準テキストのキー（GCSオブジェクト名 / ローカルファイル名）。
_REFERENCE_TEXT_NAME = "reference.txt"


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
