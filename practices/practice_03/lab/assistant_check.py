"""Run blind, read-only OpenCode checks in an isolated project snapshot."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent
ALLOWED_TOOLS = {"read", "glob", "grep"}


def digest_files(root):
    """Hash all supplied project files; OpenCode's own cache is excluded."""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".opencode" not in path.relative_to(root).parts
    }


def summarize(events):
    """Check transport/visibility/tool policy, never grade factual correctness."""
    texts = [e["part"]["text"] for e in events if e.get("type") == "text"]
    calls = [e["part"] for e in events if e.get("type") == "tool_use"]
    errors = [e for e in events if e.get("type") == "error"]
    sessions = sorted({e["sessionID"] for e in events if "sessionID" in e})
    finishes = [e["part"].get("reason") for e in events if e.get("type") == "step_finish"]
    return {
        "text": "\n".join(texts).strip(),
        "session_ids": sessions,
        "tools": [c["tool"] for c in calls],
        "tool_errors": [c for c in calls if c.get("state", {}).get("status") == "error"],
        "errors": errors,
        "last_finish": finishes[-1] if finishes else None,
        "allowed_tools_only": all(c["tool"] in ALLOWED_TOOLS for c in calls),
    }


def prepare_snapshot(target, suite):
    """Copy an explicit allowlist, excluding questions, references and results."""
    if suite == "demo":
        sources = [ROOT / "demo" / name for name in
                   ("service.py", "test_service.py", "README.md", "Makefile")]
    else:
        sources = [ROOT / name for name in ("assistant_check.py", "test_assistant_check.py")]
    for source in sources:
        shutil.copy2(source, target / source.name)
    config = json.loads((ROOT / "demo/opencode.json").read_text(encoding="utf-8"))
    prompt = (ROOT / "demo/repo-system.txt").read_text(encoding="utf-8")
    # A file manifest is navigation context, not an answer or source content.
    prompt += "\nФайлы исследуемого проекта: " + ", ".join(s.name for s in sources)
    prompt += ". Прочитай эти файлы инструментом read перед ответом.\n"
    config["agent"]["local-guide"]["prompt"] = prompt
    (target / "opencode.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("demo", "homework"), default="demo")
    parser.add_argument("--output", type=Path, required=True,
                        help="New result directory; existing runs are never overwritten")
    parser.add_argument("--question", help="One arbitrary demo prompt instead of the five questions")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    question_file = ROOT / ("QUESTIONS.md" if args.suite == "demo" else "QUESTIONS_HOMEWORK.md")
    questions = ([args.question] if args.question else
                 re.findall(r"^\d+\. (.+)$", question_file.read_text(encoding="utf-8"), re.M))
    if not questions:
        parser.error("No questions found")
    args.output.mkdir(parents=True, exist_ok=False)
    # Keep the snapshot outside the repository and never copy the answer key.
    with tempfile.TemporaryDirectory(prefix="itmo-local-check-") as directory:
        target = Path(directory)
        prepare_snapshot(target, args.suite)
        before = digest_files(target)
        env = os.environ.copy()
        for key in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_DIR"):
            env.pop(key, None)
        env.update({
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_CONFIG": str(target / "opencode.json"),
            "OPENCODE_CONFIG_CONTENT": (target / "opencode.json").read_text(encoding="utf-8"),
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_PURE": "1",
        })
        records = []
        for number, question in enumerate(questions, 1):
            command = ["opencode", "run", "--dir", str(target), "--agent", "local-guide",
                       "--model", "ollama/itmo-agent", "--format", "json", question]
            started = time.perf_counter()
            timed_out = False
            # Direct file capture preserves partial output even on timeout.
            with (args.output / f"q{number}.jsonl").open("x") as out, \
                    (args.output / f"q{number}.stderr.txt").open("x") as err:
                try:
                    result = subprocess.run(command, env=env, cwd=target, stdout=out,
                                            stderr=err, timeout=args.timeout, check=False)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    timed_out, code = True, None
            raw = (args.output / f"q{number}.jsonl").read_text(encoding="utf-8")
            try:
                events = [json.loads(line) for line in raw.splitlines() if line.strip()]
                record = summarize(events)
            except (ValueError, KeyError, TypeError) as exc:
                record = {"text": "", "errors": [str(exc)], "allowed_tools_only": False}
            record.update({"question": question, "returncode": code, "timeout": timed_out,
                           "wall_seconds": round(time.perf_counter() - started, 3)})
            record["technical_pass"] = bool(
                code == 0 and record["text"] and not record["errors"]
                and record["allowed_tools_only"] and record.get("last_finish") == "stop"
                and len(record.get("session_ids", [])) == 1
            )
            records.append(record)
            print(f"Q{number}: technical_pass={record['technical_pass']}\n{record['text']}", flush=True)
        after = digest_files(target)
        ids = [sid for r in records for sid in r.get("session_ids", [])]
        report = {"suite": args.suite, "source_sha256": before,
                  "snapshot_unchanged": before == after,
                  "unique_sessions": len(ids) == len(set(ids)) == len(questions),
                  "records": records}
        (args.output / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not (report["snapshot_unchanged"] and report["unique_sessions"]
                and all(r["technical_pass"] for r in records)):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
