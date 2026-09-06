"""録音（WAV）を評価に必要な最小限の大きさに整える（純Python・外部コマンド不要）。

スマホのブラウザは 44.1〜48kHz・ステレオで録音するため、40秒でも数MBになる。
それを5ターン分そのまま抱えると、
  - Streamlit Cloud（メモリ1GB）が評価の途中で落ちる
  - モバイル回線では送信そのものに時間がかかる
  - Gemini へ埋め込みで送れる上限（約20MB）に近づく
という形で「スマホだと失敗しやすい」状態になる。

人の声の聞き取りは 16kHz モノラルで十分（音声認識の標準）なので、送る前にそこまで
落とす。ffmpeg は Streamlit Cloud に入っていないため、標準ライブラリだけで行う。
読めない形式（float WAV など）のときは、何もせず元のデータをそのまま返す。
"""
from __future__ import annotations

import array
import io
import wave

TARGET_RATE = 16_000       # 音声認識の標準。これ以上は評価精度に効かない
TARGET_WIDTH = 2           # 16bit
_MIN_BYTES = 64 * 1024     # これより小さければ触らない（効果が無く、劣化だけ残る）


def shrink(data: bytes) -> bytes:
    """WAV を 16kHz・モノラル・16bit に落とす。失敗したら元のまま返す。"""
    if not data or len(data) < _MIN_BYTES:
        return data
    try:
        samples, rate = _decode(data)
    except Exception:  # noqa: BLE001 読めない形式は触らない（評価は元データで続ける）
        return data
    if not samples:
        return data
    if rate > TARGET_RATE:
        samples = _resample(samples, rate, TARGET_RATE)
        rate = TARGET_RATE
    out = _encode(samples, rate)
    # 小さくならないなら元のまま（無駄な変換で音を痛めない）
    return out if len(out) < len(data) else data


def _decode(data: bytes) -> tuple[array.array, int]:
    """WAV を「モノラルの16bit配列」と「サンプリング周波数」に開く。"""
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if width == 2:
        samples = array.array("h")
        samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    elif width == 1:                      # 8bit は符号なし（128が無音）
        samples = array.array("h", (int(b - 128) * 256 for b in raw))
    else:                                 # 24/32bit は扱わない（そのまま送る）
        raise ValueError(f"未対応のビット幅: {width}")

    if channels > 1:                      # ステレオはモノラルに混ぜる
        samples = _to_mono(samples, channels)
    return samples, rate


def _to_mono(samples: array.array, channels: int) -> array.array:
    out = array.array("h", bytes(2 * (len(samples) // channels)))
    for i in range(len(out)):
        base = i * channels
        out[i] = sum(samples[base:base + channels]) // channels
    return out


def _resample(samples: array.array, src_rate: int, dst_rate: int) -> array.array:
    """線形補間で間引く。音声の聞き取りにはこれで十分。"""
    n_out = int(len(samples) * dst_rate / src_rate)
    if n_out <= 0:
        return samples
    out = array.array("h", bytes(2 * n_out))
    step = len(samples) / n_out
    for i in range(n_out):
        pos = i * step
        left = int(pos)
        right = min(left + 1, len(samples) - 1)
        frac = pos - left
        out[i] = int(samples[left] * (1 - frac) + samples[right] * frac)
    return out


def _encode(samples: array.array, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(TARGET_WIDTH)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def total_size(chunks: list[bytes]) -> int:
    return sum(len(c or b"") for c in chunks)


def describe(before: int, after: int) -> str:
    """ログ用の1行（どれだけ軽くなったか）。"""
    mb = 1024 * 1024
    if before <= 0:
        return "録音なし"
    return f"録音 {before / mb:.1f}MB → {after / mb:.1f}MB（{after * 100 // before}%）"
