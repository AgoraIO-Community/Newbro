from __future__ import annotations

import pathlib
import tempfile

from newbro.cli.config_files import render_connector_config
from newbro.cli.setup_resolvers import SetupResolutionCallbacks, resolve_executor_setup_values


def _make_callbacks() -> SetupResolutionCallbacks:
    """Build a SetupResolutionCallbacks that drives the hermes branch."""
    return SetupResolutionCallbacks(
        connector_config_path=lambda: pathlib.Path(tempfile.gettempdir()) / "hermes-setup-config.yaml",
        coerce_bool_config_value=lambda value, default: default,
        existing_yaml_value=lambda raw, *path: None,
        existing_executor_node_config=lambda raw: {"enabled_executors": []},
        existing_executors_config=lambda raw: {},
        existing_connector_host_config=lambda raw: {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 8010,
            "public_base_url": "http://127.0.0.1:8000",
            "synapse_base_url": "http://127.0.0.1:8000",
            "enabled_connectors": [],
        },
        existing_connectors_config=lambda raw: {},
        existing_runtime_config=lambda raw: {},
        existing_executor_enabled_types=lambda raw: [],
        resolved_runtime_config=lambda raw, values: {},
        default_connector_host_config=lambda: {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 8010,
            "public_base_url": "http://127.0.0.1:8000",
            "synapse_base_url": "http://127.0.0.1:8000",
            "enabled_connectors": [],
        },
        render_connector_config=render_connector_config,
        pick_env_value=lambda name, existing, environ: None,
        parse_bool_value=lambda value: None,
        prompt_bool_value=lambda label, default: default,
        prompt_connector_selection=lambda: [],
        prompt_text_value=lambda label, default_value="", required=False: "hermes",
        prompt_executor_selection=lambda default_selected=None: ["hermes"],
        detected_codex_command=lambda: None,
        command_available=lambda command: True,
        resolve_agora_connector_setup_values=lambda *args, **kwargs: ({}, {}),
    )


def test_setup_writes_hermes_command_block():
    result = resolve_executor_setup_values(
        existing_values={},
        environ={},
        existing_config_yaml={},
        callbacks=_make_callbacks(),
    )
    assert result.config_text is not None
    assert "hermes" in result.config_text
    assert "command" in result.config_text
