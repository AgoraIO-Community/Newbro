from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from dataclasses import replace

from .config import load_executor_node_config
from .service import ExecutorNodeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m newbro.executors.node")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--enabled-executor",
        action="append",
        choices=["codex", "acpx"],
        help="Override the enabled executor families for this run. Repeat for multiple values.",
    )
    parser.add_argument(
        "--acpx-agent",
        help="Override the ACPX agent for this run, for example codex or openclaw.",
    )
    parser.add_argument(
        "--audio-language",
        default=None,
        help="Override local Whisper language for executor-node audio transcription, for example auto, en, or zh.",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="Override local Whisper model for executor-node audio transcription, for example base or small.",
    )
    return parser


async def _serve(service: ExecutorNodeService) -> None:
    """Run the node until cancelled, installing SIGTERM/SIGINT handlers that
    request a graceful shutdown, and always closing executors on exit."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(service.run_forever())

    def _request_stop() -> None:
        print("[stop] executor node interrupted")
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    try:
        await task
    finally:
        await service.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loaded = load_executor_node_config()
    effective_enabled_executors = list(args.enabled_executor or loaded.node_settings.enabled_executors)
    if not effective_enabled_executors:
        raise SystemExit("executor node has no local executors configured in ~/.newbro/config.yaml")
    effective_executors = dict(loaded.executors)
    if args.acpx_agent:
        acpx_config = dict(effective_executors.get("acpx") or {})
        acpx_config["agent"] = args.acpx_agent
        effective_executors["acpx"] = acpx_config
    effective_audio = dict(loaded.audio)
    if args.audio_language or args.whisper_model:
        transcription = dict(effective_audio.get("transcription") or {})
        transcription.setdefault("provider", "local_whisper")
        if args.audio_language:
            transcription["language"] = args.audio_language
        if args.whisper_model:
            transcription["model"] = args.whisper_model
        effective_audio["transcription"] = transcription
    settings = replace(
        loaded.node_settings,
        synapse_base_url=args.base_url,
        node_id=args.node_id,
        token=args.token,
        enabled_executors=effective_enabled_executors,
    )
    service = ExecutorNodeService(
        settings=settings,
        executors_config=effective_executors,
        audio_config=effective_audio,
    )
    try:
        asyncio.run(_serve(service))
    except KeyboardInterrupt:
        print("[stop] executor node interrupted")
        return 130
    except asyncio.CancelledError:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
