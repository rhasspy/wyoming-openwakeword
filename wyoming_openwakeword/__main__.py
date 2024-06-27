#!/usr/bin/env python3
import argparse
import asyncio
import logging
from functools import partial
from pathlib import Path

import openwakeword
from wyoming.server import AsyncServer

from . import __version__
from .handler import OpenWakeWordEventHandler

_LOGGER = logging.getLogger()
_DIR = Path(__file__).parent


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models-dir",
        default=_DIR / "models",
        help="Path to directory with built-in models",
    )
    parser.add_argument("--uri", default="stdio://", help="unix:// or tcp://")
    parser.add_argument(
        "--custom-model-dir",
        action="append",
        default=[],
        help="Path to directory with custom wake word models",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Wake word model threshold (0.0-1.0, default: 0.5)",
    )
    parser.add_argument("--output-dir", help="Path to save audio and detections")
    parser.add_argument(
        "--refractory-seconds",
        type=float,
        default=0.5,
        help="Seconds before the same wake word can be triggered again",
    )
    #
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )
    parser.add_argument(
        "--debug-probability",
        action="store_true",
        help="Log all wake word probabilities (VERY noisy)",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")

    args = parser.parse_args()

    if args.debug_probability:
        args.debug = True

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

    if args.version:
        print(__version__)
        return

    if args.output_dir:
        # Directory to save audio clips and chunk probabilities
        args.output_dir = Path(args.output_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Audio will be saved to %s", args.output_dir)

    models_dir = Path(args.models_dir)

    # Patch model paths
    for model_dict in (
        openwakeword.FEATURE_MODELS,
        openwakeword.VAD_MODELS,
        openwakeword.MODELS,
    ):
        for model_value in model_dict.values():
            model_path = Path(model_value["model_path"])
            model_path = models_dir / model_path.name
            model_value["model_path"] = str(model_path)

    _LOGGER.info("Ready")

    # Start server
    server = AsyncServer.from_uri(args.uri)

    try:
        await server.run(
            partial(
                OpenWakeWordEventHandler,
                models_dir,
                [Path(d) for d in args.custom_model_dir],
                args.threshold,
                args.refractory_seconds,
                Path(args.output_dir) if args.output_dir else None,
                args.debug_probability,
            )
        )
    except KeyboardInterrupt:
        pass


# -----------------------------------------------------------------------------


def run():
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
