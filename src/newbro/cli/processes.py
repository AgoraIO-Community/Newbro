from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any


@dataclass(frozen=True, slots=True)
class ManagedProcessSpec:
    name: str
    command: list[str]
    cwd: Path
    required: bool = True


def _terminate_child(process: Any, *, time_module: ModuleType, timeout: float = 5.0) -> None:
    """SIGTERM the child, wait up to `timeout`, then SIGKILL if still alive."""
    process.terminate()
    deadline = time_module.time() + timeout
    while process.poll() is None and time_module.time() < deadline:
        time_module.sleep(0.1)
    if process.poll() is None:
        process.kill()


def run_checked(
    cmd: list[str],
    *,
    cwd: Path,
    subprocess_module: ModuleType,
    signal_module: ModuleType,
    time_module: ModuleType,
) -> int:
    print(f"[run] {' '.join(cmd)}")
    process = subprocess_module.Popen(cmd, cwd=cwd)

    def _forward(_signum: int, _frame: FrameType | None) -> None:
        print("[stop] forwarding shutdown to executor node")
        _terminate_child(process, time_module=time_module)

    previous_term = signal_module.signal(signal_module.SIGTERM, _forward)
    previous_int = signal_module.signal(signal_module.SIGINT, _forward)
    try:
        returncode = process.wait()
    except KeyboardInterrupt:
        print("[stop] interrupted")
        _terminate_child(process, time_module=time_module)
        return 130
    finally:
        signal_module.signal(signal_module.SIGTERM, previous_term)
        signal_module.signal(signal_module.SIGINT, previous_int)
    if returncode in {130, -signal_module.SIGINT}:
        return 130
    if returncode != 0:
        raise SystemExit(returncode)
    return returncode


def run_managed_processes(
    commands: list[ManagedProcessSpec],
    *,
    subprocess_module: ModuleType,
    signal_module: ModuleType,
    time_module: ModuleType,
) -> int:
    processes: list[tuple[ManagedProcessSpec, Any]] = []

    def start_process(spec: ManagedProcessSpec) -> Any:
        print(f"[start] {spec.name}: {' '.join(spec.command)}")
        process = subprocess_module.Popen(spec.command, cwd=spec.cwd)
        processes.append((spec, process))
        return process

    def stop_all() -> None:
        for spec, process in reversed(processes):
            if process.poll() is None:
                print(f"[stop] {spec.name}")
                process.terminate()
        deadline = time_module.time() + 5
        for _, process in processes:
            while process.poll() is None and time_module.time() < deadline:
                time_module.sleep(0.1)
        for spec, process in processes:
            if process.poll() is None:
                print(f"[kill] {spec.name}")
                process.kill()

    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        stop_all()
        raise SystemExit(0)

    signal_module.signal(signal_module.SIGINT, handle_signal)
    signal_module.signal(signal_module.SIGTERM, handle_signal)

    for spec in commands:
        start_process(spec)

    try:
        while True:
            for spec, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"[exit] {spec.name} exited with code {code}")
                    stop_all()
                    return code
            time_module.sleep(1)
    finally:
        stop_all()
