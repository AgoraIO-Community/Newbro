from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from newbro.connectors.host.config import ConnectorConfigError, ConnectorHostSettings
from newbro.connectors.voice.agora_convoai.settings import (
    DEFAULT_STT_LANGUAGES,
    AgoraConvoAISttSettings,
    _load_agora_connector_settings_from_yaml,
)


def _loaded_config(raw_connector: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        source_path=Path("config.yaml"),
        host_settings=ConnectorHostSettings(),
        connectors={"agora-convoai": raw_connector},
    )


def test_default_stt_languages_are_chinese() -> None:
    assert AgoraConvoAISttSettings().languages == DEFAULT_STT_LANGUAGES
    assert DEFAULT_STT_LANGUAGES == ("zh-CN",)


@pytest.mark.parametrize(
    ("raw_stt", "expected"),
    [
        ({}, ("zh-CN",)),
        ({"languages": []}, ("zh-CN",)),
        ({"languages": "zh-CN, en-US"}, ("zh-CN", "en-US")),
        ({"languages": ["ja-JP", "en-US"]}, ("ja-JP", "en-US")),
    ],
)
def test_yaml_stt_languages_accept_defaults_string_and_list(raw_stt: dict[str, object], expected: tuple[str, ...]) -> None:
    settings = _load_agora_connector_settings_from_yaml(
        _loaded_config(
            {
                "app_id": "app-id",
                "app_certificate": "app-cert",
                "stt": raw_stt,
            }
        )
    )

    assert settings.stt.languages == expected


def test_yaml_stt_languages_reject_invalid_scalar() -> None:
    with pytest.raises(ConnectorConfigError, match="stt.languages"):
        _load_agora_connector_settings_from_yaml(
            _loaded_config(
                {
                    "app_id": "app-id",
                    "app_certificate": "app-cert",
                    "stt": {"languages": 123},
                }
            )
        )


def test_yaml_accepts_chat_completion_turn_silence_seconds() -> None:
    settings = _load_agora_connector_settings_from_yaml(
        _loaded_config(
            {
                "app_id": "app-id",
                "app_certificate": "app-cert",
                "chat_completion_turn_silence_seconds": 4.5,
            }
        )
    )

    assert settings.chat_completion_turn_silence_seconds == 4.5
