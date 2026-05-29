from __future__ import annotations

from types import ModuleType
from typing import Callable


def prompt_secret_value(
    name: str,
    *,
    default_value: str | None,
    getpass_module: ModuleType,
) -> str:
    while True:
        suffix = " [configured]" if default_value else ""
        entered = getpass_module.getpass(f"{name}{suffix}: ")
        if entered:
            return entered
        if default_value:
            return default_value
        print(f"{name} is required.")


def prompt_bool_value(
    label: str,
    *,
    default: bool,
    parse_bool_value: Callable[[str], bool | None],
) -> bool:
    prompt = "Y/n" if default else "y/N"
    while True:
        entered = input(f"{label} [{prompt}]: ").strip()
        if not entered:
            return default
        parsed = parse_bool_value(entered)
        if parsed is not None:
            return parsed
        print("Please answer yes or no.")


def prompt_connector_selection(
    *,
    list_available_connector_modules: Callable[[], list[str]],
    cli_error: Callable[[str], Exception],
) -> list[str]:
    connectors = list_available_connector_modules()
    if not connectors:
        raise cli_error("No connectors are currently registered.")

    print("Available connectors:")
    for index, connector in enumerate(connectors, start=1):
        print(f"  {index}. {connector}")

    while True:
        entered = input("Select connectors [1]: ").strip()
        if not entered:
            return [connectors[0]]
        selected: list[str] = []
        try:
            for part in entered.split(","):
                index = int(part.strip())
                selected.append(connectors[index - 1])
        except (ValueError, IndexError):
            print("Enter one or more numeric choices separated by commas.")
            continue
        deduped: list[str] = []
        for connector in selected:
            if connector not in deduped:
                deduped.append(connector)
        return deduped


def prompt_executor_selection(
    *,
    default_selected: list[str] | None = None,
) -> list[str]:
    executors = ["codex", "acpx"]
    print("Available detached executors:")
    for index, executor_type in enumerate(executors, start=1):
        print(f"  {index}. {executor_type}")
    default_selected = [item for item in (default_selected or [executors[0]]) if item in executors]
    if not default_selected:
        default_selected = [executors[0]]
    default_index = str(executors.index(default_selected[0]) + 1)

    while True:
        entered = input(f"Select detached executor [{default_index}]: ").strip()
        if not entered:
            return [default_selected[0]]
        try:
            index = int(entered.strip())
            return [executors[index - 1]]
        except (ValueError, IndexError):
            print("Enter one numeric choice.")


def prompt_text_value(label: str, *, default_value: str | None, required: bool = False) -> str:
    while True:
        suffix = f" [{default_value}]" if default_value else ""
        entered = input(f"{label}{suffix}: ").strip()
        if entered:
            return entered
        if default_value:
            return default_value
        if not required:
            return ""
        print(f"{label} is required.")


def prompt_choice_value(label: str, *, choices: list[str], default_value: str) -> str:
    normalized_choices = {choice.lower(): choice for choice in choices}
    while True:
        entered = input(f"{label} [{default_value}]: ").strip()
        value = (entered or default_value).lower()
        if value in normalized_choices:
            return normalized_choices[value]
        print(f"Choose one of: {', '.join(choices)}")
