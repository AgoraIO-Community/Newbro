from newbro.executors.families import SUPPORTED_EXECUTOR_FAMILIES
from newbro.runtime.config import SUPPORTED_DETACHED_EXECUTOR_TYPES


def test_hermes_is_a_supported_family():
    assert "hermes" in SUPPORTED_EXECUTOR_FAMILIES
    assert SUPPORTED_EXECUTOR_FAMILIES[:2] == ("codex", "acpx")


def test_runtime_constant_does_not_drift_from_shared_tuple():
    # The runtime constant must be the same value as the shared source of truth,
    # so settings (detached_executor_types) cannot fall out of sync.
    assert SUPPORTED_DETACHED_EXECUTOR_TYPES == SUPPORTED_EXECUTOR_FAMILIES
