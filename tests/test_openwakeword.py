"""Tests for wyoming-openwakeword"""

import asyncio
import sys
import wave
from asyncio.subprocess import PIPE
from pathlib import Path

import pytest
from wyoming.audio import AudioStart, AudioStop, wav_to_chunks
from wyoming.event import async_read_event, async_write_event
from wyoming.info import Describe, Info
from wyoming.wake import Detect, Detection, NotDetected

_DIR = Path(__file__).parent
_SAMPLES_PER_CHUNK = 1024
_DETECTION_TIMEOUT = 5


@pytest.mark.asyncio
async def test_openwakeword() -> None:
    """Test a detection with sample audio."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wyoming_openwakeword",
        "--uri",
        "stdio://",
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    # Check info
    await async_write_event(Describe().event(), proc.stdin)
    while True:
        event = await asyncio.wait_for(
            async_read_event(proc.stdout), timeout=_DETECTION_TIMEOUT
        )
        assert event is not None

        if not Info.is_type(event.type):
            continue

        info = Info.from_event(event)
        assert len(info.wake) == 1, "Expected one wake service"
        wake = info.wake[0]
        assert len(wake.models) > 0, "Expected at least one model"

        model_found = False
        for ww_model in wake.models:
            if ww_model.name == "ok_nabu_v0.1":
                assert ww_model.description == "ok nabu"
                assert ww_model.phrase == "ok nabu"
                assert ww_model.version == "v0.1"
                model_found = True
                break

        assert model_found, "Expected 'ok nabu' model"
        break

    # We want to use the 'ok nabu' model
    await async_write_event(Detect(names=["ok_nabu_v0.1"]).event(), proc.stdin)

    # Test positive WAV
    with wave.open(str(_DIR / "ok_nabu.wav"), "rb") as ok_nabu_wav:
        await async_write_event(
            AudioStart(
                rate=ok_nabu_wav.getframerate(),
                width=ok_nabu_wav.getsampwidth(),
                channels=ok_nabu_wav.getnchannels(),
            ).event(),
            proc.stdin,
        )
        for chunk in wav_to_chunks(ok_nabu_wav, _SAMPLES_PER_CHUNK):
            await async_write_event(chunk.event(), proc.stdin)

    await async_write_event(AudioStop().event(), proc.stdin)

    while True:
        event = await asyncio.wait_for(
            async_read_event(proc.stdout), timeout=_DETECTION_TIMEOUT
        )
        if event is None:
            proc.stdin.close()
            _, stderr = await proc.communicate()
            assert False, stderr.decode()

        if not Detection.is_type(event.type):
            continue

        detection = Detection.from_event(event)
        assert detection.name == "ok_nabu_v0.1"  # success
        break

    # Test negative WAV
    with wave.open(str(_DIR / "snowboy.wav"), "rb") as snowboy_wav:
        await async_write_event(
            AudioStart(
                rate=snowboy_wav.getframerate(),
                width=snowboy_wav.getsampwidth(),
                channels=snowboy_wav.getnchannels(),
            ).event(),
            proc.stdin,
        )
        for chunk in wav_to_chunks(snowboy_wav, _SAMPLES_PER_CHUNK):
            await async_write_event(chunk.event(), proc.stdin)

    await async_write_event(AudioStop().event(), proc.stdin)

    while True:
        event = await asyncio.wait_for(async_read_event(proc.stdout), timeout=1)
        if event is None:
            proc.stdin.close()
            _, stderr = await proc.communicate()
            assert False, stderr.decode()

        if not NotDetected.is_type(event.type):
            continue

        # Should receive a not-detected message after audio-stop
        break

    # Need to close stdin for graceful termination
    proc.stdin.close()
    _, stderr = await proc.communicate()

    assert proc.returncode == 0, stderr.decode()
