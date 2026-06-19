from __future__ import annotations

import io
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_DIR = Path("test-results")
SUMMARY_FILE = REPORT_DIR / "summary.md"
JSON_FILE = REPORT_DIR / "results.json"

COVERAGE_NOTES = [
    "Parses synthetic BNZ CSV exports from multiple accounts.",
    "Filters transactions to the requested month.",
    "Detects matching internal transfers and exports one iCost transfer row.",
    "Classifies known merchants and local rule matches.",
    "Keeps AI classification opt-in and limited to Payee-only merchant strings.",
    "Writes iCost-compatible XLSX headers and shared strings.",
    "Writes an unknown workbook when classification is unclear.",
]


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.successes: list[unittest.case.TestCase] = []

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        super().addSuccess(test)
        self.successes.append(test)


class RecordingRunner(unittest.TextTestRunner):
    resultclass = RecordingResult


def test_label(test: unittest.case.TestCase) -> str:
    return f"{test.__class__.__name__}.{test._testMethodName}"


def failure_items(items: list[tuple[unittest.case.TestCase, str]]) -> list[dict[str, str]]:
    return [{"test": test_label(test), "traceback": traceback} for test, traceback in items]


def build_summary(result: RecordingResult, output: str) -> str:
    status = "passed" if result.wasSuccessful() else "failed"
    lines = [
        "# CI Test Report",
        "",
        f"- Status: **{status}**",
        f"- Tests run: **{result.testsRun}**",
        f"- Passed: **{len(result.successes)}**",
        f"- Failures: **{len(result.failures)}**",
        f"- Errors: **{len(result.errors)}**",
        f"- Skipped: **{len(result.skipped)}**",
        "",
        "## What This CI Checks",
        "",
    ]
    lines.extend(f"- {note}" for note in COVERAGE_NOTES)
    lines.extend(["", "## Test Cases", ""])
    lines.extend(f"- PASS `{test_label(test)}`" for test in result.successes)
    lines.extend(f"- FAIL `{test_label(test)}`" for test, _ in result.failures)
    lines.extend(f"- ERROR `{test_label(test)}`" for test, _ in result.errors)

    if result.failures or result.errors:
        lines.extend(["", "## Failure Details", ""])
        for test, traceback in result.failures + result.errors:
            lines.extend([f"### `{test_label(test)}`", "", "```text", traceback.strip(), "```", ""])

    lines.extend(["", "## Raw unittest Output", "", "```text", output.strip(), "```", ""])
    return "\n".join(lines)


def main() -> int:
    REPORT_DIR.mkdir(exist_ok=True)
    suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
    stream = io.StringIO()
    runner = RecordingRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    output = stream.getvalue()

    sys.stdout.write(output)
    summary = build_summary(result, output)
    SUMMARY_FILE.write_text(summary, encoding="utf-8")

    JSON_FILE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "passed" if result.wasSuccessful() else "failed",
                "tests_run": result.testsRun,
                "passed": [test_label(test) for test in result.successes],
                "failures": failure_items(result.failures),
                "errors": failure_items(result.errors),
                "skipped": [{"test": test_label(test), "reason": reason} for test, reason in result.skipped],
                "coverage_notes": COVERAGE_NOTES,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as handle:
            handle.write(summary)
            handle.write("\n")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
