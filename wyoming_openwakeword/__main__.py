#!/usr/bin/env python3
import argparse
import asyncio
import logging
import re
from functools import partial
from pathlib import Path

from wyoming.server import AsyncServer, AsyncTcpServer

from . import __version__
from .handler import OpenWakeWordEventHandler
from .state import State

_LOGGER = logging.getLogger()
_NAME_VERSION = re.compile(r"^([^_]+)_v[0-9.]+$")


async def main() -> None:
    parser = argparse.ArgumentParser()
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
    parser.add_argument(
        "--trigger-level",
        type=int,
        default=1,
        help="Number of activations before detection (default: 1)",
    )
    parser.add_argument(
        "--refractory-seconds",
        type=float,
        default=2.0,
        help="Seconds before a wake word can be detected again (default: 2)",
    )
    #
    parser.add_argument(
        "--zeroconf",
        nargs="?",
        const="openWakeWord",
        help="Enable discovery over zeroconf with optional name (default: openWakeWord)",
    )
    #
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    parser.add_argument(
        "--log-format", default=logging.BASIC_FORMAT, help="Format for log messages"
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    #
    parser.add_argument("--model", action="append", default=[], help="Deprecated")
    parser.add_argument("--models-dir", help="Deprecated")
    parser.add_argument("--preload-model", action="append", help="Deprecated")
    parser.add_argument("--output-dir", help="Deprecated")
    parser.add_argument("--debug-probability", action="store_true", help="Deprecated")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format=args.log_format
    )
    _LOGGER.debug(args)

    if args.version:
        print(__version__)
        return

    state = State()

    # Look for custom wake word models
    for custom_model_dir_str in args.custom_model_dir:
        custom_model_dir = Path(custom_model_dir_str)
        for model_path in custom_model_dir.glob("*.tflite"):
            model_id = model_path.stem
            name_match = _NAME_VERSION.match(model_id)
            if name_match:
                # Remove version
                model_id = name_match.group(1)

            if model_id in state.custom_models:
                continue

            state.custom_models[model_id] = model_path
            _LOGGER.debug("Found custom model %s at %s", model_id, model_path)

    _LOGGER.info("Ready")

    # Start server
    server = AsyncServer.from_uri(args.uri)

    if args.zeroconf:
        if not isinstance(server, AsyncTcpServer):
            raise ValueError("Zeroconf requires tcp:// uri")

        from wyoming.zeroconf import HomeAssistantZeroconf

        tcp_server: AsyncTcpServer = server
        hass_zeroconf = HomeAssistantZeroconf(
            name=args.zeroconf, port=tcp_server.port, host=tcp_server.host
        )
        await hass_zeroconf.register_server()
        _LOGGER.debug("Zeroconf discovery enabled")

    try:
        await server.run(
            partial(
                OpenWakeWordEventHandler,
                args.threshold,
                args.trigger_level,
                args.refractory_seconds,
                state,
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
