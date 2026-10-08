"""Offline integrity verification of the final saved OpenCode runs."""

import json
from pathlib import Path
import tempfile

from assistant_check import ROOT, digest_files, prepare_snapshot, summarize


def main():
    sessions = []
    runs = (
        ("review-demo-20261006", "demo", 5),
        ("review-homework-20261006", "homework", 5),
        ("live-demo-20261006", "demo", 1),
    )
    for name, suite, count in runs:
        directory = ROOT / "results" / name
        report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        if report["suite"] != suite or len(report["records"]) != count:
            raise SystemExit(f"{name}: unexpected suite or question count")
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary)
            prepare_snapshot(snapshot, suite)
            if digest_files(snapshot) != report["source_sha256"]:
                raise SystemExit(f"{name}: source/config changed since the run; rerun required")
        if not report["snapshot_unchanged"] or not report["unique_sessions"]:
            raise SystemExit(f"{name}: snapshot/session checks failed")
        for number, record in enumerate(report["records"], 1):
            events = [json.loads(line) for line in
                      (directory / f"q{number}.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip()]
            actual = summarize(events)
            if any(record[key] != value for key, value in actual.items()):
                raise SystemExit(f"{name}/q{number}: summary differs from raw events")
            if not (record["technical_pass"] and record["returncode"] == 0
                    and not record["timeout"] and actual["text"]
                    and not actual["errors"] and actual["allowed_tools_only"]
                    and actual["last_finish"] == "stop" and len(actual["session_ids"]) == 1):
                raise SystemExit(f"{name}/q{number}: technical checks failed")
            sessions.extend(actual["session_ids"])
        print(f"{name}: {count} logs verified, current source/config hashes match")
    if len(sessions) != len(set(sessions)):
        raise SystemExit("Sessions overlap between final runs")
    print(f"OK: {len(sessions)} independent sessions; semantic grading is in REPORT.md")


if __name__ == "__main__":
    main()
