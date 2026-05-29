from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newbro.yaml_support import load_yaml_file


@dataclass(slots=True)
class EnvTemplateLine:
    raw: str
    key: str | None = None
    value: str | None = None
    commented: bool = False


@dataclass(slots=True)
class ConnectorSetupResult:
    env_values: dict[str, str | None]
    config_path: Path | None = None
    config_text: str | None = None


@dataclass(slots=True)
class SetupValuesResult:
    env_values: dict[str, str | None]
    runtime_values: dict[str, object]


def parse_env_template_lines(raw_lines: tuple[str, ...]) -> list[EnvTemplateLine]:
    parsed: list[EnvTemplateLine] = []
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped or "=" not in stripped:
            parsed.append(EnvTemplateLine(raw=raw))
            continue
        commented = stripped.startswith("#")
        assignment = stripped[1:].strip() if commented else stripped
        key, _, value = assignment.partition("=")
        key = key.strip()
        if not key:
            parsed.append(EnvTemplateLine(raw=raw))
            continue
        parsed.append(
            EnvTemplateLine(
                raw=raw,
                key=key,
                value=value.strip(),
                commented=commented,
            )
        )
    return parsed


def load_env_template(default_lines: tuple[str, ...]) -> list[EnvTemplateLine]:
    return parse_env_template_lines(default_lines)


def bootstrap_env_template(
    default_lines: tuple[str, ...],
    *,
    required_key: str | None = None,
) -> list[EnvTemplateLine]:
    bootstrapped: list[EnvTemplateLine] = []
    for line in load_env_template(default_lines):
        if line.key == required_key:
            bootstrapped.append(
                EnvTemplateLine(raw=f"{line.key}=", key=line.key, value="", commented=False)
            )
            continue
        bootstrapped.append(
            EnvTemplateLine(raw=line.raw, key=line.key, value=line.value, commented=line.commented)
        )
    return bootstrapped


def load_env_assignments(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    order: list[str] = []
    if not path.exists():
        return values, order
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = value
        order.append(key)
    return values, order


def write_env_file(
    *,
    template_lines: list[EnvTemplateLine],
    resolved_values: dict[str, str | None],
    existing_values: dict[str, str],
    existing_order: list[str],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    known_keys = [line.key for line in template_lines if line.key is not None]
    rendered_lines: list[str] = []

    for line in template_lines:
        if line.key is None:
            rendered_lines.append(line.raw)
            continue

        resolved_value = resolved_values.get(line.key)
        if resolved_value is None or resolved_value == "":
            if line.commented:
                rendered_lines.append(line.raw)
            elif line.value is not None:
                rendered_lines.append(f"{line.key}={line.value}")
            else:
                rendered_lines.append(f"{line.key}=")
            continue

        rendered_lines.append(f"{line.key}={resolved_value}")

    unknown_keys = [key for key in existing_order if key not in known_keys]
    additional_resolved_keys = [
        key
        for key, value in resolved_values.items()
        if key not in known_keys and key not in unknown_keys and value not in (None, "")
    ]
    if unknown_keys:
        if rendered_lines and rendered_lines[-1] != "":
            rendered_lines.append("")
        for key in unknown_keys:
            rendered_lines.append(f"{key}={existing_values[key]}")
    if additional_resolved_keys:
        if rendered_lines and rendered_lines[-1] != "":
            rendered_lines.append("")
        for key in additional_resolved_keys:
            rendered_lines.append(f"{key}={resolved_values[key]}")

    destination.write_text("\n".join(rendered_lines) + "\n", encoding="utf-8")


def pick_env_value(name: str, existing_values: dict[str, str], environ: dict[str, str]) -> str | None:
    return environ.get(name) or existing_values.get(name)


def normalize_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_required_value(value: str | None, *, placeholder: str | None) -> str | None:
    stripped = normalize_optional_value(value)
    if stripped is None or stripped == placeholder:
        return None
    return stripped


def parse_bool_value(raw_value: str, *, truthy_values: set[str], falsy_values: set[str]) -> bool | None:
    normalized = raw_value.strip().lower()
    if normalized in truthy_values:
        return True
    if normalized in falsy_values:
        return False
    return None


def format_bool(value: bool) -> str:
    return "true" if value else "false"


def resolve_setup_values(
    *,
    template_lines: list[EnvTemplateLine],
    existing_values: dict[str, str],
    environ: dict[str, str],
    interactive: bool,
    interactive_setup_keys: set[str],
    openai_key: str,
    openai_placeholder: str,
    env_file_label: str,
    prompt_secret_value,
    cli_error,
) -> SetupValuesResult:
    resolved: dict[str, str | None] = {}

    for line in template_lines:
        if line.key is None or line.key in interactive_setup_keys:
            continue
        current_value = pick_env_value(line.key, existing_values, environ)
        if current_value is None and not line.commented:
            current_value = line.value
        resolved[line.key] = normalize_optional_value(current_value)

    openai_default = normalize_required_value(
        pick_env_value(openai_key, existing_values, environ),
        placeholder=openai_placeholder,
    )
    if interactive:
        resolved[openai_key] = prompt_secret_value(openai_key, default_value=openai_default)
    else:
        if openai_default is None:
            raise cli_error(
                f"{openai_key} is required for non-interactive setup. Set it in {env_file_label} or the shell environment."
            )
        resolved[openai_key] = openai_default

    return SetupValuesResult(env_values=resolved, runtime_values={})


def resolve_bootstrap_values(
    *,
    template_lines: list[EnvTemplateLine],
    existing_values: dict[str, str],
    interactive_setup_keys: set[str],
    openai_key: str,
) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}

    for line in template_lines:
        if line.key is None or line.key in interactive_setup_keys:
            continue
        current_value = existing_values.get(line.key)
        if current_value is None and not line.commented:
            current_value = line.value
        resolved[line.key] = normalize_optional_value(current_value)

    resolved[openai_key] = normalize_optional_value(existing_values.get(openai_key))
    return resolved


def render_connector_config(
    *,
    runtime: dict[str, object],
    connector_host: dict[str, object],
    connectors: dict[str, dict[str, object]],
    executor_node: dict[str, object] | None = None,
    executors: dict[str, dict[str, object]] | None = None,
) -> str:
    lines = ["version: 1", ""]
    if runtime:
        lines.append("runtime:")
        lines.extend(render_yaml_mapping(runtime, indent=2))
    else:
        lines.append("runtime: {}")
    lines.extend(["", "connector_host:"])
    lines.extend(render_yaml_mapping(connector_host, indent=2))
    lines.append("")
    if connectors:
        lines.append("connectors:")
        lines.extend(render_yaml_mapping(connectors, indent=2))
    else:
        lines.append("connectors: {}")
    lines.extend(["", "executor_node:"])
    lines.extend(render_yaml_mapping(executor_node or {"enabled_executors": []}, indent=2))
    lines.append("")
    if executors:
        lines.append("executors:")
        lines.extend(render_yaml_mapping(executors, indent=2))
    else:
        lines.append("executors: {}")
    return "\n".join(lines) + "\n"


def render_yaml_mapping(mapping: dict[str, object], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            if value:
                lines.append(f"{prefix}{key}:")
                lines.extend(render_yaml_mapping(value, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {{}}")
        elif isinstance(value, list):
            if value:
                lines.append(f"{prefix}{key}:")
                for item in value:
                    lines.append(f"{prefix}  - {render_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{key}: []")
        else:
            lines.append(f"{prefix}{key}: {render_yaml_scalar(value)}")
    return lines


def render_yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if ":" in text or "#" in text or "\n" in text:
        return f'"{text}"'
    return text


def load_existing_connector_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    loaded = load_yaml_file(path)
    if isinstance(loaded, dict):
        return loaded
    return {}


def load_existing_connector_yaml_for_setup(path: Path) -> tuple[dict[str, object], str | None]:
    try:
        return load_existing_connector_yaml(path), None
    except Exception as exc:
        return {}, str(exc)


def existing_yaml_value(raw_connector_yaml: dict[str, object], *path: str) -> str | None:
    value: object = raw_connector_yaml
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value in (None, ""):
        return None
    return str(value)


def existing_connector_block(raw_connector_yaml: dict[str, object], connector: str) -> dict[str, object]:
    raw_connectors = raw_connector_yaml.get("connectors")
    if not isinstance(raw_connectors, dict):
        return {}
    raw_connector = raw_connectors.get(connector)
    if not isinstance(raw_connector, dict):
        return {}
    return raw_connector


def existing_nested_value(raw_connector: dict[str, object], *path: str) -> str | None:
    value: object = raw_connector
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value in (None, ""):
        return None
    return str(value)


def existing_executor_enabled_types(raw_connector_yaml: dict[str, object]) -> list[str]:
    raw_executor_node = raw_connector_yaml.get("executor_node")
    if not isinstance(raw_executor_node, dict):
        return []
    raw_types = raw_executor_node.get("enabled_executors")
    if not isinstance(raw_types, list):
        return []
    return [
        item.strip()
        for item in raw_types
        if isinstance(item, str) and item.strip()
    ]


def coerce_bool_config_value(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        parsed = parse_bool_value(
            value,
            truthy_values={"1", "true", "yes", "on", "y"},
            falsy_values={"0", "false", "no", "off", "n"},
        )
        if parsed is not None:
            return parsed
    return default


def existing_runtime_config(raw_connector_yaml: dict[str, object], *, removed_keys: set[str]) -> dict[str, object]:
    raw_runtime = raw_connector_yaml.get("runtime")
    if not isinstance(raw_runtime, dict):
        return {}
    return {
        key: value
        for key, value in raw_runtime.items()
        if key not in removed_keys
    }


def default_connector_host_config() -> dict[str, object]:
    return {
        "enabled": False,
        "host": "0.0.0.0",
        "port": 8010,
        "public_base_url": "http://127.0.0.1:8000",
        "synapse_base_url": "http://127.0.0.1:8000",
        "enabled_connectors": [],
    }


def default_executor_node_config() -> dict[str, object]:
    return {
        "enabled_executors": [],
    }


def existing_connector_host_config(raw_connector_yaml: dict[str, object]) -> dict[str, object]:
    raw_host = raw_connector_yaml.get("connector_host")
    if isinstance(raw_host, dict):
        return dict(raw_host)
    return default_connector_host_config()


def existing_connectors_config(raw_connector_yaml: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_connectors = raw_connector_yaml.get("connectors")
    if not isinstance(raw_connectors, dict):
        return {}
    return {
        key: value
        for key, value in raw_connectors.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def existing_executor_node_config(raw_connector_yaml: dict[str, object]) -> dict[str, object]:
    raw_executor_node = raw_connector_yaml.get("executor_node")
    if isinstance(raw_executor_node, dict):
        return {
            "enabled_executors": existing_executor_enabled_types(raw_connector_yaml),
        }
    return default_executor_node_config()


def existing_executors_config(raw_connector_yaml: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_executors = raw_connector_yaml.get("executors")
    if not isinstance(raw_executors, dict):
        return {}
    return {
        key: value
        for key, value in raw_executors.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def resolved_runtime_config(
    raw_connector_yaml: dict[str, object],
    runtime_values: dict[str, object] | None,
    *,
    removed_keys: set[str],
) -> dict[str, object]:
    resolved = existing_runtime_config(raw_connector_yaml, removed_keys=removed_keys)
    for key, value in (runtime_values or {}).items():
        if value in (None, ""):
            resolved.pop(key, None)
            continue
        resolved[key] = value
    return resolved


def write_connector_config_if_needed(
    result: ConnectorSetupResult,
    *,
    format_user_path,
) -> None:
    if result.config_path is None or result.config_text is None:
        return
    result.config_path.parent.mkdir(parents=True, exist_ok=True)
    result.config_path.write_text(result.config_text, encoding="utf-8")
    print(f"[write] configured {format_user_path(result.config_path)}")
