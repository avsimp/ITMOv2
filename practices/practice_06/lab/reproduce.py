"""Reproduce both phases without replacing the working service or losing its fixes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from prompt_injection_probe import opencode_chat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASELINE = "0c8a9c1"  # Course revision before the security fixes.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="openai/gpt-6.1-sol")
    parser.add_argument("--http-only", action="store_true")
    args = parser.parse_args()
    original = subprocess.check_output(
        ["git", "show", BASELINE + ":practices/practice_06/lab/service.py"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="shop-baseline-") as directory:
        baseline = Path(directory) / "service.py"
        baseline.write_bytes(original)
        for phase, service in [("before", baseline), ("after", HERE / "service.py")]:
            common = ["--phase", phase, "--service", str(service)]
            subprocess.run([sys.executable, "-B", str(HERE / "audit.py"), *common], check=True)
            if not args.http_only:
                subprocess.run([sys.executable, "-B", str(HERE / "prompt_injection_probe.py"),
                                *common, "--model", args.model], check=True)
    if not args.http_only:
        context = (ROOT / "THREAT_MODEL.md").read_text()
        result = opencode_chat(args.model, context, "threat-judge", "Оцени приложенную модель угроз по своим критериям. Верни JSON.")
        evidence = {"model": args.model, "runner": "opencode threat-judge",
                    "system_prompt_sha256": hashlib.sha256((ROOT / "judge-system-prompt.md").read_bytes()).hexdigest(),
                    "input": context, "raw_response": result}
        try:
            evidence["parsed"] = json.loads(result["message"]["content"])
        except ValueError:
            evidence["parse_error"] = "Response is not JSON; see raw_response"
        (ROOT / "evidence/judge/threat-model-review.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
