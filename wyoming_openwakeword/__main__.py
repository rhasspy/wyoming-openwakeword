#!/usr/bin/env python3
import argparse
import asyncio
import logging
from functools import partial
from pathlib import Path
from threading import Thread

from wyoming.server import AsyncServer

from .handler import OpenWakeWordEventHandler, ensure_loaded
from .openwakeword import embeddings_proc, mels_proc
from .state import State

_LOGGER = logging.getLogger()
_DIR = Path(__file__).parent


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="stdio://", help="unix:// or tcp://")
    parser.add_argument(
        "--models-dir",
        default=_DIR / "models",
        help="Path to directory with built-in models",
    )
    parser.add_argument(
        "--custom-model-dir",
        action="append",
        default=[],
        help="Path to directory with custom wake word models",
    )
    parser.add_argument(
        "--preload-model",
        action="append",
        default=[],
        help="Name or path of wake word model(s) to pre-load",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Wake word model threshold (0-1, default: 0.5)",
    )
    parser.add_argument(
        "--trigger-level",
        type=int,
        default=1,
        help="Number of activations before detection (default: 4)",
    )
    #
    parser.add_argument("--output-dir", help="Path to save audio and detections")
    #
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--debug-probability",
        action="store_true",
        help="Log all wake word probabilities (VERY noisy)",
    )
    #
    parser.add_argument("--model", action="append", default=[], help="Deprecated")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug(args)

    if args.output_dir:
        # Directory to save audio clips and chunk probabilities
        args.output_dir = Path(args.output_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Audio will be saved to %s", args.output_dir)

    # Resolve wake word model paths
    state = State(
        models_dir=Path(args.models_dir),
        custom_model_dirs=[Path(d) for d in args.custom_model_dir],
        debug_probability=args.debug_probability,
        output_dir=args.output_dir,
    )

    # Pre-load models
    ensure_loaded(
        state,
        args.preload_model,
        threshold=args.threshold,
        trigger_level=args.trigger_level,
    )

    # audio -> mels
    mels_thread = Thread(target=mels_proc, daemon=True, args=(state,))
    mels_thread.start()

    # mels -> embeddings
    embeddings_thread = Thread(target=embeddings_proc, daemon=True, args=(state,))
    embeddings_thread.start()
    _LOGGER.info("Ready")

    # Start server
    server = AsyncServer.from_uri(args.uri)

    try:
        await server.run(partial(OpenWakeWordEventHandler, args, state))
    except KeyboardInterrupt:
        pass
    finally:
        # Graceful shutdown
        _LOGGER.debug("Shutting down")
        state.is_running = False
        state.audio_ready.release()
        mels_thread.join()

        state.mels_ready.release()
        embeddings_thread.join()

        for ww_name, ww_state in state.wake_words.items():
            ww_state.embeddings_ready.release()
            state.ww_threads[ww_name].join()


# -----------------------------------------------------------------------------


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
