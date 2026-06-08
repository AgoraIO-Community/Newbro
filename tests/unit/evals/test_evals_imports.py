from __future__ import annotations

from evals.run import build_argument_parser
from evals.communication.runner import CommunicationEvalResult, format_results


def test_evals_import_under_current_newbro_package_name():
    parser = build_argument_parser()
    parsed = parser.parse_args(["communication"])

    result = CommunicationEvalResult(
        scenario="smoke",
        reply_text="ok",
        tool_names=[],
        passed_expected_tools=True,
        passed_forbidden_tools=True,
        mechanical_reply=False,
        passed_mock_only_reply_rules=True,
    )

    assert parsed.suite == "communication"
    assert '"scenario": "smoke"' in format_results([result])
