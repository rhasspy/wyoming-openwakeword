"""Event handler for clients of the server."""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from pyopen_wakeword import Model, OpenWakeWord, OpenWakeWordFeatures
from wyoming.audio import AudioChunk, AudioChunkConverter, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler
from wyoming.wake import Detect, Detection, NotDetected

from . import __version__
from .state import State

_LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = Model.OKAY_NABU


@dataclass
class Detector:
    id: str
    oww_model: OpenWakeWord
    triggers_left: int
    is_detected: bool = False
    last_triggered: Optional[float] = None


class OpenWakeWordEventHandler(AsyncEventHandler):
    """Event handler for openWakeWord clients."""

    def __init__(
        self,
        threshold: float,
        trigger_level: int,
        refractory_seconds: float,
        state: State,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.client_id = str(time.monotonic_ns())
        self.threshold = threshold
        self.trigger_level = trigger_level
        self.refractory_seconds = refractory_seconds
        self.state = state
        self.converter = AudioChunkConverter(rate=16000, width=2, channels=1)
        self.oww_features = OpenWakeWordFeatures.from_builtin()
        self.audio_buffer = bytes()
        self.detectors: Dict[str, Detector] = {}
        self.audio_timestamp = 0

        _LOGGER.debug("Client connected: %s", self.client_id)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            info = self._get_info()
            await self.write_event(info.event())
            _LOGGER.debug("Sent info to client: %s", self.client_id)
            return True

        if Detect.is_type(event.type):
            detect = Detect.from_event(event)
            ww_names = set()
            if detect.names:
                for ww_name in detect.names:
                    if ww_name in self.state.custom_models:
                        ww_names.add(ww_name)
                    else:
                        try:
                            model = Model(ww_name)
                            ww_names.add(ww_name)
                        except ValueError:
                            continue

            if not ww_names:
                ww_names.add(DEFAULT_MODEL.value)

            for ww_name in ww_names:
                if ww_name in self.detectors:
                    continue

                oww_model: Optional[OpenWakeWord] = None
                model_path = self.state.custom_models.get(ww_name)
                if model_path is not None:
                    oww_model = OpenWakeWord.from_model(model_path)
                else:
                    try:
                        model = Model(ww_name)
                        oww_model = OpenWakeWord.from_builtin(model)
                    except ValueError:
                        pass

                if not oww_model:
                    continue

                self.detectors[ww_name] = Detector(
                    id=ww_name,
                    oww_model=oww_model,
                    triggers_left=self.trigger_level,
                )

            # Remove unnecessary detectors
            for other_ww_name in set(self.detectors.keys()) - ww_names:
                self.detectors.pop(other_ww_name)

            _LOGGER.debug("Loaded models: %s", list(self.detectors.keys()))
        elif AudioStart.is_type(event.type):
            _LOGGER.debug("Receiving audio from client: %s", self.client_id)

            # Reset
            self.audio_timestamp = 0
            self.oww_features.reset()
            for detector in self.detectors.values():
                detector.is_detected = False
                detector.triggers_left = self.trigger_level
                detector.last_triggered = None
                detector.oww_model.reset()
        elif AudioChunk.is_type(event.type):
            chunk = self.converter.convert(AudioChunk.from_event(event))
            for features in self.oww_features.process_streaming(chunk.audio):
                for detector in self.detectors.values():
                    skip_detector = (detector.last_triggered is not None) and (
                        (time.monotonic() - detector.last_triggered)
                        < self.refractory_seconds
                    )

                    # Still need to process features even if we skip detection
                    for prob in detector.oww_model.process_streaming(features):
                        if skip_detector:
                            continue

                        if prob <= self.threshold:
                            continue

                        detector.triggers_left -= 1
                        if detector.triggers_left > 0:
                            continue

                        detector.is_detected = True
                        detector.last_triggered = time.monotonic()
                        await self.write_event(
                            Detection(
                                name=detector.id, timestamp=self.audio_timestamp
                            ).event()
                        )
                        _LOGGER.debug(
                            "Detected %s at %s", detector.id, self.audio_timestamp
                        )

            self.audio_timestamp += chunk.milliseconds
        elif AudioStop.is_type(event.type):
            # Inform client if no detections occurred
            if not any(detector.is_detected for detector in self.detectors.values()):
                # No wake word detections
                await self.write_event(NotDetected().event())

                _LOGGER.debug(
                    "Audio stopped without detection from client: %s", self.client_id
                )
        else:
            _LOGGER.debug("Unexpected event: type=%s, data=%s", event.type, event.data)

        return True

    async def disconnect(self) -> None:
        _LOGGER.debug("Client disconnected: %s", self.client_id)

    def _get_info(self) -> Info:
        models: List[WakeModel] = []
        for model in Model:
            phrase = _get_phrase(model.value)
            models.append(
                WakeModel(
                    name=model.value,
                    description=phrase,
                    phrase=phrase,
                    attribution=Attribution(
                        name="dscripka",
                        url="https://github.com/dscripka/openWakeWord",
                    ),
                    installed=True,
                    languages=["en"],
                    version="v0.1",
                )
            )

        for custom_model in self.state.custom_models:
            phrase = _get_phrase(custom_model)
            models.append(
                WakeModel(
                    name=custom_model,
                    description=phrase,
                    phrase=phrase,
                    attribution=Attribution(
                        name="",
                        url="",
                    ),
                    installed=True,
                    languages=[],
                    version="",
                )
            )

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
                    models=models,
                )
            ],
        )


def _get_phrase(name: str) -> str:
    phrase = name.lower().strip().replace("_", " ")
    phrase = " ".join(w.capitalize() for w in phrase.split())
    return phrase
