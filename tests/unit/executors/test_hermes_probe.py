from newbro.executors.adapters.hermes.probe import parse_hermes_version, interpret_hermes_auth_list


def test_parse_version_extracts_semver():
    assert parse_hermes_version("hermes 1.4.2") == "1.4.2"


def test_parse_version_handles_missing():
    assert parse_hermes_version("") is None


def test_auth_list_with_credentials_is_authenticated():
    out = "copilot (1 credentials):\n  #1  gh auth token  api_key gh_cli\n"
    assert interpret_hermes_auth_list(returncode=0, output=out) is True


def test_auth_list_empty_is_unauthenticated():
    assert interpret_hermes_auth_list(returncode=0, output="\n") is False


def test_auth_list_failure_is_unknown():
    assert interpret_hermes_auth_list(returncode=1, output="boom") is None
