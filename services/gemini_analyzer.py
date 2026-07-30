"""Gemini API による動画・音声解析。

動画/音声を Files API でアップロードし、core.prompts のプロンプトで
5 項目評価＋タイムスタンプ付き Before/After を JSON 生成、
core.models.EvaluationResult として返す。
"""
from __future__ import annotations

import json
import re
import subprocess
import time

from google import genai
from google.genai import types

from config import settings
from core import prompts
from core.models import EvaluationResult

# 動画アップロード後 ACTIVE になるまでのポーリング設定
_POLL_INTERVAL_SEC = 2
_POLL_TIMEOUT_SEC = 300

# 出力(JSON)の上限。長尺の商談でも途中で切れにくいよう広めに取る。
_MAX_OUTPUT_TOKENS = 32768

# JSON厳守を促す追記（リトライ時にプロンプト末尾へ付ける）
_STRICT_JSON = ("\n\n重要：応答は有効なJSONオブジェクトのみを返すこと。"
                "途中で切らず、コードフェンス(```)や前後の説明文を一切付けない。")


def _loads_lenient(text: str) -> dict:
    """Gemini 応答を JSON として頑健に読む。

    - ```json フェンスや前後の余計な文字（Extra data）を除去して parse する。
    - まず素直に、失敗したら最初の { 〜 最後の } を切り出して再挑戦する。
    - 途中切断（Unterminated＝閉じ括弧が無い）はここでは直せないため、
      呼び出し側で1回だけ再生成リトライする。
    """
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise


# 長尺動画でトークン（無料枠）を使い切らないよう、総フレーム数の目安をこの値に抑える。
_TARGET_FRAMES = 1600
_FPS_MIN, _FPS_MAX = 0.15, 0.5


def _probe_duration_sec(path: str) -> float | None:
    """動画の長さ(秒)を ffmpeg で調べる。取れなければ None。"""
    try:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([ff, "-i", path], capture_output=True, text=True, timeout=120)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", r.stderr or "")
        if m:
            h, mn, s = (int(x) for x in m.groups())
            return float(h * 3600 + mn * 60 + s)
    except Exception:  # noqa: BLE001
        pass
    return None


def _target_fps(path: str) -> float:
    """動画の長さに応じたフレーム取得fpsを返す（短い商談は密に、長尺は間引く）。

    総フレーム数が _TARGET_FRAMES 程度になるよう fps を決め、0.15〜0.5 にクランプする。
    長さが取れない場合は既定 GEMINI_VIDEO_FPS。表情の変化は数秒単位なので、fpsを
    下げても表情・身振りは十分読める（映像は捨てない）。
    """
    dur = _probe_duration_sec(path)
    if not dur or dur <= 0:
        return settings.GEMINI_VIDEO_FPS
    return max(_FPS_MIN, min(_FPS_MAX, _TARGET_FRAMES / dur))


# 429（無料枠のレート上限）で待って再試行する秒数。分あたり上限は待てば復旧する。
_RATE_LIMIT_WAITS = [30, 60]


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "resource_exhausted", "resourceexhausted",
                                "quota", "rate limit", "rate_limit"))


def _generate_retrying(client: genai.Client, contents: list, cfg):
    """generate_content を実行。429 のときだけ待って再試行する（他エラーは即送出）。"""
    last: Exception | None = None
    for wait in [0, *_RATE_LIMIT_WAITS]:
        if wait:
            time.sleep(wait)
        try:
            return client.models.generate_content(
                model=settings.GEMINI_MODEL, contents=contents, config=cfg)
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_rate_limit(e):
                raise
    raise last  # type: ignore[misc]


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


def _media_part(uploaded, fps: float | None = None):
    """動画は低fpsでフレームを間引いた Part にし、音声などはそのまま渡す。

    身振り手振り・表情は残しつつトークンを抑え、2〜3時間の長尺でも上限に収まりやすくする。
    fps 未指定なら既定 GEMINI_VIDEO_FPS。
    """
    mime = getattr(uploaded, "mime_type", "") or ""
    if mime.startswith("video/"):
        return types.Part(
            file_data=types.FileData(file_uri=uploaded.uri, mime_type=mime),
            video_metadata=types.VideoMetadata(fps=fps or settings.GEMINI_VIDEO_FPS),
        )
    return uploaded


def analyze(
    video_path: str,
    reference_talk: str | None = None,
    knowledge_base: str | None = None,
) -> EvaluationResult:
    """動画/音声ファイルを解析し EvaluationResult を返す。"""
    client = _client()

    # 映像は残す（表情など非言語も評価に使う）。長尺は動画の長さから fps を自動計算して
    # フレームを間引き、表情の変化は追えるままトークン（＝無料枠）消費を抑える。
    fps = _target_fps(video_path)
    uploaded = client.files.upload(file=video_path)
    uploaded = _wait_until_active(client, uploaded)

    prompt = prompts.build_evaluation_prompt(reference_talk, knowledge_base)

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        # 映像解像度は下げてトークンを節約（表情・身振りは十分読める）。
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )
    try:
        resp = _generate_retrying(client, [_media_part(uploaded, fps), prompt], cfg)
        data = _loads_lenient(resp.text)
    except json.JSONDecodeError:
        # 途中切断/不正JSONのことがあるため、JSON厳守を促して1回だけ再試行する。
        resp = _generate_retrying(
            client, [_media_part(uploaded, fps), prompt + _STRICT_JSON], cfg)
        data = _loads_lenient(resp.text)
    finally:
        # 解析後はアップロード済みファイルを後始末（失敗しても致命的ではない）
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

    return EvaluationResult.from_dict(data)


def analyze_roleplay(
    audio_turns: list[bytes],
    scenario_lines: list[str],
    talk_script: str | None = None,
    knowledge_base: str | None = None,
    mime_type: str = "audio/wav",
    focus: str | None = None,
    persona: dict | None = None,
) -> EvaluationResult:
    """1人ロープレの録音（ターンごと）をまとめて1回の呼び出しで評価する。

    会話中は AI を呼ばず台本で進めるため、Gemini の呼び出しはこの1回だけ＝無料枠にやさしい。
    """
    client = _client()
    prompt = prompts.build_roleplay_prompt(scenario_lines, talk_script, knowledge_base, focus, persona)

    contents: list = []
    for i, data in enumerate(audio_turns, 1):
        if not data:
            continue
        contents.append(f"--- T{i}（お客様「{scenario_lines[i-1]}」への応答）---"
                        if i <= len(scenario_lines) else f"--- T{i} ---")
        contents.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    contents.append(prompt)

    cfg = types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )
    try:
        resp = _generate_retrying(client, contents, cfg)
        data = _loads_lenient(resp.text)
    except json.JSONDecodeError:
        resp = _generate_retrying(client, contents + [_STRICT_JSON], cfg)
        data = _loads_lenient(resp.text)
    return EvaluationResult.from_dict(data)


_REFINE_PROMPT = (
    "あなたは住宅リフォームのトップ営業兼トークコーチです。次の営業トークスクリプトを、"
    "実際にお客様の前で話しやすいように整文してください。\n"
    "ルール：\n"
    "- 意味・伝える情報・話す順番は変えない（勝手に内容を足さない/消さない）。\n"
    "- くどい言い回し・重複・冗長な相槌を削り、自然な話し言葉に整える。\n"
    "- お客様目線で分かりやすく、専門用語には一言添える程度に。\n"
    "- 【見出し】や「Q.」などの構造・記号はそのまま残す。\n"
    "- 出力は整文後の本文のみ（説明や前置きは書かない）。日本語。"
)


def refine_talk_script(text: str, model: str | None = None) -> str:
    """営業コーチ視点でトークスクリプトを整文した案を返す（Gemini 1回）。"""
    client = _client()
    resp = client.models.generate_content(
        model=model or settings.MINUTES_EXTRACT_MODEL,
        contents=_REFINE_PROMPT + "\n\n---元のスクリプト---\n" + (text or "")[:12000],
    )
    return (resp.text or "").strip()


# 模範トーク動画を「テキスト基準」に変換するためのプロンプト
_REFERENCE_TRANSCRIBE_PROMPT = (
    "この動画は住宅営業の『模範商談』です。後輩が学べる基準テキストを作ってください。\n"
    "1) 営業担当の実際のトークを、お客様とのやり取りの流れがわかる形で文字起こしする。\n"
    "2) 最後に『この模範トークの要点（間の取り方・感情の拾い方・刺さる言い回し）』を箇条書きで添える。\n"
    "出力はプレーンテキストのみ。"
)


def transcribe_reference(video_path: str) -> str:
    """模範トーク動画を、評価基準に使える『テキスト』へ変換して返す。

    重い動画は保存せず、この軽いテキストだけを蓄積するために使う（容量対策）。
    """
    client = _client()
    uploaded = client.files.upload(file=video_path)
    uploaded = _wait_until_active(client, uploaded)
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[_media_part(uploaded), _REFERENCE_TRANSCRIBE_PROMPT],
            config=types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            ),
        )
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
    return (response.text or "").strip()
