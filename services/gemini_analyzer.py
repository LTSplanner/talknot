"""Gemini API による動画・音声解析。

動画/音声を Files API でアップロードし、core.prompts のプロンプトで
5 項目評価＋タイムスタンプ付き Before/After を JSON 生成、
core.models.EvaluationResult として返す。
"""
from __future__ import annotations

import json
import time

from google import genai
from google.genai import types

from config import settings
from core import prompts
from core.models import EvaluationResult

# 動画アップロード後 ACTIVE になるまでのポーリング設定
_POLL_INTERVAL_SEC = 2
_POLL_TIMEOUT_SEC = 300


def _client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY が未設定です（.env を確認してください）。")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _wait_until_active(client: genai.Client, file):
    """アップロードした動画が解析可能（ACTIVE）になるまで待つ。"""
    waited = 0
    while file.state.name == "PROCESSING":
        if waited >= _POLL_TIMEOUT_SEC:
            raise TimeoutError("動画の処理がタイムアウトしました。")
        time.sleep(_POLL_INTERVAL_SEC)
        waited += _POLL_INTERVAL_SEC
        file = client.files.get(name=file.name)
    if file.state.name == "FAILED":
        raise RuntimeError("動画の処理に失敗しました。")
    return file


def analyze(video_path: str, reference_talk: str | None = None) -> EvaluationResult:
    """動画/音声ファイルを解析し EvaluationResult を返す。"""
    client = _client()

    uploaded = client.files.upload(file=video_path)
    uploaded = _wait_until_active(client, uploaded)

    prompt = prompts.build_evaluation_prompt(reference_talk)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=[uploaded, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # 動画は声・間が読めれば十分。映像解像度を下げてトークン消費を大幅削減し、
            # 長尺の商談録画でも上限/無料枠に当たりにくくする（軽量化重視）。
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        ),
    )

    # 解析後はアップロード済みファイルを後始末（失敗しても致命的ではない）
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    data = json.loads(response.text)
    return EvaluationResult.from_dict(data)
