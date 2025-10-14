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
_CUSTOM_MODEL_DIR = _DIR / "custom_models"
_SAMPLES_PER_CHUNK = 1024
_DETECTION_TIMEOUT = 5

MODELS_TO_TEST = [
    "okay_nabu",
    "hey_jarvis",
    "hey_mycroft",
    "hey_rhasspy",
    "alexa",
    "computer",
]


@pytest.mark.asyncio
async def test_openwakeword() -> None:
    """Test a detection with sample audio."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wyoming_openwakeword",
        "--uri",
        "stdio://",
        "--custom-model-dir",
        str(_CUSTOM_MODEL_DIR),
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

        missing_models = set(MODELS_TO_TEST)
        for ww_model in wake.models:
            missing_models.discard(ww_model.name)

        assert not missing_models, f"Missing models: {missing_models}"
        break

    # Listen for multiple wake words
    await async_write_event(Detect(names=MODELS_TO_TEST).event(), proc.stdin)

    # Test positive WAV
    for ww_model in MODELS_TO_TEST:
        with wave.open(str(_DIR / f"{ww_model}.wav"), "rb") as wav_file:
            await async_write_event(
                AudioStart(
                    rate=wav_file.getframerate(),
                    width=wav_file.getsampwidth(),
                    channels=wav_file.getnchannels(),
                ).event(),
                proc.stdin,
            )
            for chunk in wav_to_chunks(wav_file, _SAMPLES_PER_CHUNK):
                await async_write_event(chunk.event(), proc.stdin)

        await async_write_event(AudioStop().event(), proc.stdin)

        while True:
            try:
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
                assert detection.name == ww_model  # success
                break
            except TimeoutError as err:
                raise TimeoutError(f"Timeout while waiting for {ww_model}") from err

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
        try:
            event = await asyncio.wait_for(async_read_event(proc.stdout), timeout=1)
            if event is None:
                proc.stdin.close()
                _, stderr = await proc.communicate()
                assert False, stderr.decode()

            if not NotDetected.is_type(event.type):
                continue

            # Should receive a not-detected message after audio-stop
            break
        except TimeoutError as err:
            raise TimeoutError(
                "Timeout while waiting for not-detected message"
            ) from err

    # Need to close stdin for graceful termination
    proc.stdin.close()
    _, stderr = await proc.communicate()

    assert proc.returncode == 0, stderr.decode()
