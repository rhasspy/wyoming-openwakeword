"""Event handler for clients of the server."""
import argparse
import asyncio
import logging
import re
import time
import wave
from pathlib import Path
from threading import Thread
from typing import List, Optional

import numpy as np
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler
from wyoming.wake import Detect, NotDetected

from .const import ClientData, WakeWordData
from .openwakeword import ww_proc
from .state import State, WakeWordState

_LOGGER = logging.getLogger(__name__)
_WAKE_WORD_WITH_VERSION = re.compile(r"^(.+)_(v[0-9.]+)$")


class OpenWakeWordEventHandler(AsyncEventHandler):
    """Event handler for openWakeWord clients."""

    def __init__(
        self,
        cli_args: argparse.Namespace,
        state: State,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.client_id = str(time.monotonic_ns())
        self.state = state
        self.data: Optional[ClientData] = None
        self.converter = AudioChunkConverter(rate=16000, width=2, channels=1)
        self.audio_buffer = bytes()

        # Only used when output_dir is set
        self.audio_writer: Optional[wave.Wave_write] = None

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            info = self._get_info()
            await self.write_event(info.event())
            _LOGGER.debug("Sent info to client: %s", self.client_id)
            return True

        if self.data is None:
            # Create buffers for this client
            self.data = ClientData(self)
            with self.state.clients_lock:
                self.state.clients[self.client_id] = self.data
                for ww_name in self.state.wake_words:
                    self.data.wake_words[ww_name] = WakeWordData(
                        threshold=self.cli_args.threshold,
                        trigger_level=self.cli_args.trigger_level,
                    )

        if Detect.is_type(event.type):
            detect = Detect.from_event(event)
            if detect.names:
                ensure_loaded(
                    self.state,
                    detect.names,
                    threshold=self.cli_args.threshold,
                    trigger_level=self.cli_args.trigger_level,
                )
        elif AudioStart.is_type(event.type):
            # Reset
            for ww_data in self.data.wake_words.values():
                ww_data.is_detected = False

            with self.state.audio_lock:
                self.data.reset()

            _LOGGER.debug("Receiving audio from client: %s", self.client_id)

            if self.cli_args.output_dir is not None:
                audio_start = AudioStart.from_event(event)
                audio_path = Path(self.cli_args.output_dir) / f"{self.client_id}.wav"
                self.audio_writer = wave.open(str(audio_path), "wb")
                self.audio_writer.setframerate(audio_start.rate)
                self.audio_writer.setsampwidth(audio_start.width)
                self.audio_writer.setnchannels(audio_start.channels)
                _LOGGER.debug("Saving audio to %s", audio_path)

        elif AudioChunk.is_type(event.type):
            # Add to audio buffer and signal mels thread
            chunk = self.converter.convert(AudioChunk.from_event(event))

            if self.audio_writer is not None:
                self.audio_writer.writeframes(chunk.audio)

            chunk_array = np.frombuffer(chunk.audio, dtype=np.int16).astype(np.float32)

            with self.state.audio_lock:
                # Shift samples left
                self.data.audio[: -len(chunk_array)] = self.data.audio[
                    len(chunk_array) :
                ]

                # Add new samples to end
                self.data.audio[-len(chunk_array) :] = chunk_array
                self.data.new_audio_samples = min(
                    len(self.data.audio),
                    self.data.new_audio_samples + len(chunk_array),
                )

                self.data.audio_timestamp = chunk.timestamp or time.monotonic_ns()

            # Signal mels thread that audio is ready to process
            self.state.audio_ready.release()
        elif AudioStop.is_type(event.type):
            # Inform client if not detections occurred
            if not any(
                ww_data.is_detected for ww_data in self.data.wake_words.values()
            ):
                # No wake word detections
                await self.write_event(NotDetected().event())

                _LOGGER.debug(
                    "Audio stopped without detection from client: %s", self.client_id
                )

            if self.audio_writer is not None:
                self.audio_writer.close()
                self.audio_writer = None

            return False
        else:
            _LOGGER.debug("Unexpected event: type=%s, data=%s", event.type, event.data)

        return True

    async def disconnect(self) -> None:
        _LOGGER.debug("Client disconnected: %s", self.client_id)

        if self.audio_writer is not None:
            self.audio_writer.close()
            self.audio_writer = None

        if self.data is None:
            return

        with self.state.clients_lock:
            self.state.clients.pop(self.client_id, None)

    def _get_info(self) -> Info:
        return Info(
            wake=[
                WakeProgram(
                    name="openwakeword",
                    description="An open-source audio wake word (or phrase) detection framework with a focus on performance and simplicity.",
                    attribution=Attribution(
                        name="dscripka", url="https://github.com/dscripka/openWakeWord"
                    ),
                    installed=True,
                    models=[
                        WakeModel(
                            name=model_path.stem,
                            # hey_jarvis_v0.1 => hey jarvis
                            description=_get_description(model_path.stem),
                            attribution=Attribution(
                                name="dscripka",
                                url="https://github.com/dscripka/openWakeWord",
                            ),
                            installed=True,
                            languages=[],
                        )
                        for model_path in _get_wake_word_files(self.state)
                    ],
                )
            ],
        )


# -----------------------------------------------------------------------------


def ensure_loaded(state: State, names: List[str], threshold: float, trigger_level: int):
    """Ensure wake words are loaded by name."""
    with state.ww_threads_lock, state.clients_lock:
        for model_key in names:
            norm_model_key = _normalize_key(model_key)

            ww_state = state.wake_words.get(model_key)
            if ww_state is not None:
                # Already loaded
                continue

            model_paths = _get_wake_word_files(state)
            model_path: Optional[Path] = None
            for maybe_model_path in model_paths:
                if norm_model_key == _normalize_key(maybe_model_path.stem):
                    # Exact match
                    model_path = maybe_model_path
                    break

                if match := _WAKE_WORD_WITH_VERSION.match(maybe_model_path.stem):
                    # Exclude version
                    if norm_model_key == _normalize_key(match.group(1)):
                        model_path = maybe_model_path
                        break

            if model_path is None:
                raise ValueError(f"Wake word model not found: {model_key}")

            # Start thread for model
            state.wake_words[model_key] = WakeWordState()
            state.ww_threads[model_key] = Thread(
                target=ww_proc,
                daemon=True,
                args=(
                    state,
                    model_key,
                    model_path,
                    asyncio.get_running_loop(),
                ),
            )
            state.ww_threads[model_key].start()

            for client_data in state.clients.values():
                client_data.wake_words[model_key] = WakeWordData(
                    threshold=threshold,
                    trigger_level=trigger_level,
                )

            _LOGGER.debug("Started thread for %s", model_key)


# -----------------------------------------------------------------------------


def _get_wake_word_files(state: State) -> List[Path]:
    """Get paths to all available wake word model files."""
    model_paths = [
        p
        for p in state.models_dir.glob("*.tflite")
        if _WAKE_WORD_WITH_VERSION.match(p.stem)
    ]

    for custom_model_dir in state.custom_model_dirs:
        model_paths.extend(custom_model_dir.glob("*.tflite"))

    return model_paths


def _normalize_key(model_key: str) -> str:
    """Normalize model key for comparison."""
    return model_key.lower().replace("_", " ").strip()


def _get_description(file_name: str) -> str:
    """Get human-readable description of a wake word from model name."""
    if match := _WAKE_WORD_WITH_VERSION.match(file_name):
        # Remove version
        file_name = match.group(1)

    return file_name.replace("_", " ")
