from newbro.executors.adapters.hermes.probe import parse_hermes_version


def test_parse_version_extracts_semver():
    assert parse_hermes_version("hermes 1.4.2") == "1.4.2"


def test_parse_version_handles_missing():
    assert parse_hermes_version("") is None
