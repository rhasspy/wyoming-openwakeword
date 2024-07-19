"""Event handler for clients of the server."""
import logging
import re
import time
import wave
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Dict, FrozenSet, List, Optional, Set

import numpy as np
import openwakeword
from openwakeword.model import Model
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler
from wyoming.wake import Detect, Detection, NotDetected

from . import __version__
from .const import Settings

_LOGGER = logging.getLogger(__name__)
_WAKE_WORD_WITH_VERSION = re.compile(r"^(.+)_(v[0-9.]+)$")

_CACHED_MODELS: Dict[FrozenSet[str], List[Model]] = defaultdict(list)
_CACHED_MODELS_LOCK = Lock()


class OpenWakeWordEventHandler(AsyncEventHandler):
    """Event handler for openWakeWord clients."""

    def __init__(self, settings: Settings, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.settings = settings
        self.client_id = str(time.monotonic_ns())

        # openWakeWord object.
        # Pulled from cache if possible (_CACHED_MODELS).
        self.model: Optional[Model] = None

        # Key for model in cache.
        # This is the set of model paths that are loaded.
        self.model_cache_key: Optional[FrozenSet[str]] = None

        # Timestamp when a model can be triggered again
        self.model_wait_time: Dict[str, float] = {}

        # Audio resampler
        self.converter = AudioChunkConverter(rate=16000, width=2, channels=1)

        # Timestamp of most recent audio chunk
        self.last_timestamp: Optional[int] = None

        # True if at least one detection occurred between audio start/stop
        self.has_detections = False

        # Model names to listen for (empty = all)
        self.detect_names: Set[str] = set()

        # Saves audio for debugging.
        # Only used when output_dir is set.
        self.audio_writer: Optional[wave.Wave_write] = None

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            info = self._get_info()
            await self.write_event(info.event())
            _LOGGER.debug("Sent info to client: %s", self.client_id)
            return True

        if Detect.is_type(event.type):
            detect = Detect.from_event(event)
            if detect.names:
                # Only detect these wake word models
                self.detect_names.update(detect.names)
        elif AudioStart.is_type(event.type):
            if self.model is None:
                self._init_model()

            # Reset
            self.model.reset()
            self.last_timestamp = None
            self.has_detections = False
            self.detect_names.clear()
            self.model_wait_time.clear()

            _LOGGER.debug("Receiving audio from client: %s", self.client_id)

            if self.settings.output_dir is not None:
                audio_start = AudioStart.from_event(event)
                audio_path = Path(self.settings.output_dir) / f"{self.client_id}.wav"
                self.audio_writer = wave.open(str(audio_path), "wb")
                self.audio_writer.setframerate(audio_start.rate)
                self.audio_writer.setsampwidth(audio_start.width)
                self.audio_writer.setnchannels(audio_start.channels)
                _LOGGER.debug("Saving audio to %s", audio_path)

        elif AudioChunk.is_type(event.type):
            if self.model is None:
                self._init_model()
            assert self.model is not None
            chunk = self.converter.convert(AudioChunk.from_event(event))
            self.last_timestamp = chunk.timestamp

            if self.audio_writer is not None:
                self.audio_writer.writeframes(chunk.audio)

            chunk_array = np.frombuffer(chunk.audio, dtype=np.int16).astype(np.float32)

            self.model.predict(chunk_array)
            for model_name in self.model.prediction_buffer:
                if self.detect_names and (model_name not in self.detect_names):
                    _LOGGER.debug("Skipping detection of %s", model_name)
                    continue

                scores = list(self.model.prediction_buffer[model_name])
                if scores[-1] > self.settings.detection_threshold:
                    model_time = self.model_wait_time.get(model_name)
                    if (model_time is not None) and (time.monotonic() < model_time):
                        # Within refractory period
                        continue

                    self.model_wait_time[model_name] = (
                        time.monotonic() + self.settings.refractory_seconds
                    )
                    _LOGGER.debug("Detected: %s", model_name)
                    await self.write_event(
                        Detection(
                            name=model_name, timestamp=self.last_timestamp
                        ).event()
                    )

                if self.settings.debug_probability:
                    _LOGGER.debug("%s: %s", model_name, scores[-1])

        elif AudioStop.is_type(event.type):
            # Inform client if no detections occurred
            if not self.has_detections:
                await self.write_event(NotDetected().event())

                _LOGGER.debug(
                    "Audio stopped without detection from client: %s", self.client_id
                )

            self._close_audio_writer()
            self._return_model_to_cache()
        else:
            _LOGGER.debug("Unexpected event: type=%s, data=%s", event.type, event.data)

        return True

    async def disconnect(self) -> None:
        _LOGGER.debug("Client disconnected: %s", self.client_id)

        self._close_audio_writer()
        self._return_model_to_cache()

    def _close_audio_writer(self) -> None:
        if self.audio_writer is not None:
            self.audio_writer.close()
            self.audio_writer = None

    def _init_model(self) -> None:
        if self.model is None:
            # Try to load from cache first
            wakeword_models = [str(p) for p in self._get_wakeword_model_paths()]
            self.model_cache_key = frozenset(wakeword_models)
            with _CACHED_MODELS_LOCK:
                cached_models = _CACHED_MODELS.get(self.model_cache_key)
                if cached_models:
                    self.model = cached_models.pop()

            if self.model is None:
                # Load openWakeWord models
                _LOGGER.debug("Loading openWakeWord models: %s", wakeword_models)
                self.model = Model(
                    wakeword_models=wakeword_models,
                    inference_framework="tflite",
                    melspec_model_path=openwakeword.FEATURE_MODELS[
                        "melspectrogram"
                    ]["model_path"],
                    embedding_model_path=openwakeword.FEATURE_MODELS["embedding"][
                        "model_path"
                    ],
                    vad_threshold=self.settings.vad_threshold,
                )

    def _return_model_to_cache(self) -> None:
        if (self.model is not None) and (self.model_cache_key is not None):
            with _CACHED_MODELS_LOCK:
                _CACHED_MODELS[self.model_cache_key].append(self.model)

        self.model = None
        self.model_cache_key = None

    def _get_wakeword_model_paths(self) -> List[Path]:
        model_paths = self._get_model_paths()
        if not self.detect_names:
            # All models
            return model_paths

        detect_model_paths: List[Path] = []
        for model_name in self.detect_names:
            norm_model_name = _normalize_key(model_name)
            for maybe_model_path in model_paths:
                if norm_model_name == _normalize_key(maybe_model_path.stem):
                    # Exact match
                    detect_model_paths.append(maybe_model_path)
                    break

                if match := _WAKE_WORD_WITH_VERSION.match(maybe_model_path.stem):
                    # Exclude version
                    if norm_model_name == _normalize_key(match.group(1)):
                        detect_model_paths.append(maybe_model_path)
                        break

        return detect_model_paths

    def _get_model_paths(self) -> List[Path]:
        model_paths: List[Path] = [
            p
            for p in self.settings.builtin_models_dir.glob("*.tflite")
            if _WAKE_WORD_WITH_VERSION.match(p.stem)
        ]

        for custom_model_dir in self.settings.custom_model_dirs:
            model_paths.extend(custom_model_dir.glob("*.tflite"))

        return model_paths

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
                    version=__version__,
                    models=[
                        WakeModel(
                            name=model_path.stem,
                            # hey_jarvis_v0.1 => hey jarvis
                            description=_get_description(model_path.stem),
                            phrase=_get_description(model_path.stem),
                            attribution=Attribution(
                                name="dscripka",
                                url="https://github.com/dscripka/openWakeWord",
                            ),
                            installed=True,
                            languages=[],
                            version=_get_version(model_path.stem),
                        )
                        for model_path in self._get_model_paths()
                    ],
                )
            ],
        )


# -----------------------------------------------------------------------------


def _normalize_key(model_key: str) -> str:
    """Normalize model key for comparison."""
    return model_key.lower().replace("_", " ").strip()


def _get_description(file_name: str) -> str:
    """Get human-readable description of a wake word from model name."""
    if match := _WAKE_WORD_WITH_VERSION.match(file_name):
        # Remove version
        file_name = match.group(1)

    return file_name.replace("_", " ")


def _get_version(file_name: str) -> Optional[str]:
    """Get version of a wake word from model name."""
    if match := _WAKE_WORD_WITH_VERSION.match(file_name):
        # Extract version
        return match.group(2)

    return None
