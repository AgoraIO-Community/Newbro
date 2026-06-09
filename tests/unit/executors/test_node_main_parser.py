# tests/unit/executors/test_node_main_parser.py
from newbro.executors.node.__main__ import build_parser


def test_node_parser_accepts_enabled_executor_hermes():
    parser = build_parser()
    args = parser.parse_args(["--base-url", "u", "--node-id", "n", "--token", "t", "--enabled-executor", "hermes"])
    assert args.enabled_executor == ["hermes"]
