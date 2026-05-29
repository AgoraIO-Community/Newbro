from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class SetupContext:
    cli_name: str
    root_launcher: str
    env_file: Path


@dataclass(frozen=True, slots=True)
class SetupCallbacks:
    setup_can_prompt: Callable[[], bool]
    bootstrap_setup_files: Callable[[], None]
    load_env_template: Callable[[], list[object]]
    load_env_assignments: Callable[[Path], tuple[dict[str, str], list[str]]]
    connector_config_path: Callable[[], Path]
    load_existing_connector_yaml_for_setup: Callable[[Path], tuple[dict[str, object], str | None]]
    load_existing_connector_yaml: Callable[[Path], dict[str, object]]
    resolve_setup_values: Callable[..., object]
    resolve_connector_setup_values: Callable[..., object]
    resolve_executor_setup_values: Callable[..., object]
    render_connector_config: Callable[..., str]
    resolved_runtime_config: Callable[[dict[str, object], dict[str, object] | None], dict[str, object]]
    existing_connector_host_config: Callable[[dict[str, object]], dict[str, object]]
    existing_connectors_config: Callable[[dict[str, object]], dict[str, dict[str, object]]]
    existing_executor_node_config: Callable[[dict[str, object]], dict[str, object]]
    existing_executors_config: Callable[[dict[str, object]], dict[str, dict[str, object]]]
    write_env_file: Callable[..., None]
    write_connector_config_if_needed: Callable[[object], None]
    connector_setup_result: Callable[..., object]
    format_user_path: Callable[[Path], str]
    cli_error: Callable[[str], Exception]
    environ: object
    legacy_real_executor_env_keys: set[str]


def run_setup(args, context: SetupContext, callbacks: SetupCallbacks) -> int:
    if args.bootstrap_defaults:
        callbacks.bootstrap_setup_files()
        return 0
    if not args.non_interactive and not callbacks.setup_can_prompt():
        raise callbacks.cli_error(
            f"{context.cli_name} setup requires a TTY. Use --non-interactive for automation."
        )

    template_lines = callbacks.load_env_template()
    existing_values, existing_order = callbacks.load_env_assignments(context.env_file)
    config_path = callbacks.connector_config_path()
    existing_config_yaml, config_load_error = callbacks.load_existing_connector_yaml_for_setup(config_path)
    if config_load_error is not None:
        print(
            f"[warn] ignoring invalid existing config at {callbacks.format_user_path(config_path)}: {config_load_error}"
        )
    setup_values = callbacks.resolve_setup_values(
        template_lines=template_lines,
        existing_values=existing_values,
        environ=callbacks.environ,
        interactive=not args.non_interactive,
        existing_config_yaml=existing_config_yaml,
    )
    connector_setup = callbacks.resolve_connector_setup_values(
        existing_values=existing_values,
        environ=callbacks.environ,
        interactive=not args.non_interactive,
        force_prompt=False,
        existing_config_yaml=existing_config_yaml,
        runtime_values=setup_values.runtime_values,
    )
    callbacks.write_env_file(
        template_lines=template_lines,
        resolved_values={**setup_values.env_values, **connector_setup.env_values},
        existing_values=existing_values,
        existing_order=existing_order,
        destination=context.env_file,
    )
    config_setup = connector_setup if connector_setup.config_text is not None else callbacks.connector_setup_result(env_values={})
    if config_setup.config_text is None and (config_load_error is not None or setup_values.runtime_values or not config_path.exists()):
        config_setup = callbacks.connector_setup_result(
            env_values={},
            config_path=config_path,
            config_text=callbacks.render_connector_config(
                runtime=callbacks.resolved_runtime_config(existing_config_yaml, setup_values.runtime_values),
                connector_host=callbacks.existing_connector_host_config(existing_config_yaml),
                connectors=callbacks.existing_connectors_config(existing_config_yaml),
                executor_node=callbacks.existing_executor_node_config(existing_config_yaml),
                executors=callbacks.existing_executors_config(existing_config_yaml),
            ),
        )
    callbacks.write_connector_config_if_needed(config_setup)
    print(f"[write] configured {callbacks.format_user_path(context.env_file)}")
    return 0


def run_connector_setup(_args, context: SetupContext, callbacks: SetupCallbacks) -> int:
    if not callbacks.setup_can_prompt():
        raise callbacks.cli_error(f"{context.cli_name} connector setup requires a TTY.")

    template_lines = callbacks.load_env_template()
    existing_values, existing_order = callbacks.load_env_assignments(context.env_file)
    existing_config_yaml = callbacks.load_existing_connector_yaml(callbacks.connector_config_path())
    connector_setup = callbacks.resolve_connector_setup_values(
        existing_values=existing_values,
        environ=callbacks.environ,
        interactive=True,
        force_prompt=True,
        existing_config_yaml=existing_config_yaml,
        runtime_values=None,
    )
    callbacks.write_env_file(
        template_lines=template_lines,
        resolved_values={**existing_values, **connector_setup.env_values},
        existing_values=existing_values,
        existing_order=existing_order,
        destination=context.env_file,
    )
    callbacks.write_connector_config_if_needed(connector_setup)
    print(f"[write] configured {callbacks.format_user_path(context.env_file)}")
    return 0


def run_executor_setup(_args, context: SetupContext, callbacks: SetupCallbacks) -> int:
    if not callbacks.setup_can_prompt():
        raise callbacks.cli_error(f"{context.cli_name} executor setup requires a TTY.")
    run_executor_setup_flow(context, callbacks)
    return 0


def run_executor_setup_flow(context: SetupContext, callbacks: SetupCallbacks) -> None:
    template_lines = callbacks.load_env_template()
    existing_values, existing_order = callbacks.load_env_assignments(context.env_file)
    existing_config_yaml = callbacks.load_existing_connector_yaml(callbacks.connector_config_path())
    executor_setup = callbacks.resolve_executor_setup_values(
        existing_values=existing_values,
        environ=callbacks.environ,
        existing_config_yaml=existing_config_yaml,
    )
    filtered_existing_values = {
        key: value
        for key, value in existing_values.items()
        if key not in callbacks.legacy_real_executor_env_keys
    }
    filtered_existing_order = [
        key for key in existing_order if key not in callbacks.legacy_real_executor_env_keys
    ]
    callbacks.write_env_file(
        template_lines=template_lines,
        resolved_values={**filtered_existing_values, **executor_setup.env_values},
        existing_values=filtered_existing_values,
        existing_order=filtered_existing_order,
        destination=context.env_file,
    )
    callbacks.write_connector_config_if_needed(executor_setup)
    print(f"[write] configured {callbacks.format_user_path(context.env_file)}")
