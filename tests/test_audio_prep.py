"""録音を軽くする処理のテスト。

スマホの録音が大きすぎて評価が落ちる事故を防ぐための処理なので、
「ちゃんと小さくなる」「音の長さが変わらない」「壊れた入力で落ちない」を守る。
"""
import array
import io
import math
import wave

import pytest

from core import audio_prep


def _wav(seconds=5.0, rate=48000, channels=2, width=2, hz=440):
    n = int(seconds * rate)
    a = array.array("h", bytes(2 * n * channels))
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * hz * i / rate))
        for c in range(channels):
            a[i * channels + c] = v
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(a.tobytes())
    return buf.getvalue()


def _info(data):
    with wave.open(io.BytesIO(data)) as w:
        return {"rate": w.getframerate(), "channels": w.getnchannels(),
                "seconds": w.getnframes() / w.getframerate()}


class TestItGetsSmaller:
    @pytest.mark.parametrize("rate,channels", [(48000, 2), (48000, 1), (44100, 2), (44100, 1)])
    def test_phone_recordings_shrink_a_lot(self, rate, channels):
        """スマホの標準的な録音が、少なくとも半分以下になる。"""
        src = _wav(rate=rate, channels=channels)
        out = audio_prep.shrink(src)
        assert len(out) < len(src) / 2

    def test_result_is_16k_mono(self):
        out = audio_prep.shrink(_wav(rate=48000, channels=2))
        assert _info(out)["rate"] == audio_prep.TARGET_RATE
        assert _info(out)["channels"] == 1

    def test_length_is_preserved(self):
        """長さが変わると、どのセリフへの応答か対応が崩れる。"""
        out = audio_prep.shrink(_wav(seconds=7.0, rate=48000))
        assert abs(_info(out)["seconds"] - 7.0) < 0.05

    def test_already_small_audio_is_left_alone(self):
        """16kHzモノラルはこれ以上落とさない（劣化だけ残るため）。"""
        src = _wav(rate=16000, channels=1)
        assert audio_prep.shrink(src) == src

    def test_eight_bit_audio_is_handled(self):
        n = 44100 * 3
        raw = bytes((128 + int(100 * math.sin(i / 20)) for i in range(n)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(44100)
            w.writeframes(raw)
        out = audio_prep.shrink(buf.getvalue())
        assert _info(out)["rate"] == audio_prep.TARGET_RATE


class TestItNeverBreaksTheEvaluation:
    @pytest.mark.parametrize("bad", [b"", b"not a wav at all" * 9000, b"RIFF" + b"\x00" * 90000])
    def test_broken_input_is_passed_through(self, bad):
        """読めない録音は触らずそのまま渡す（評価を止めない）。"""
        assert audio_prep.shrink(bad) == bad

    def test_tiny_input_is_untouched(self):
        src = _wav(seconds=0.2, rate=48000)
        assert audio_prep.shrink(src) == src

    def test_unsupported_bit_depth_is_passed_through(self):
        """24/32bit（float録音など）は変換せずそのまま送る。"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(4)
            w.setframerate(48000)
            w.writeframes(b"\x00\x01\x02\x03" * 30000)
        src = buf.getvalue()
        assert audio_prep.shrink(src) == src


def test_a_five_turn_session_fits_well_under_the_inline_limit():
    """5ターン分でも、Geminiに埋め込める上限（約20MB）に余裕をもって収まる。"""
    turns = [audio_prep.shrink(_wav(seconds=40, rate=48000, channels=2)) for _ in range(5)]
    assert audio_prep.total_size(turns) < 8 * 1024 * 1024


def test_describe_reads_as_a_log_line():
    assert "%" in audio_prep.describe(10 * 1024 * 1024, 2 * 1024 * 1024)
    assert audio_prep.describe(0, 0) == "録音なし"
