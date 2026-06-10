from newbro.executors.adapters.hermes import HermesExecutor


def test_capabilities_are_core_run_loop_only():
    caps = HermesExecutor(command="hermes").get_capabilities()
    assert caps.executor_type == "hermes"
    assert caps.supports_follow_up is True
    assert caps.supports_cancel is True
    assert caps.supports_pause is False
    assert caps.supports_resume is False
    assert caps.supports_thread_list is False
    assert caps.supports_audio_instruction is False
    assert caps.skills == []
