"""Controlled local Ollama experiment; standard library only."""
import argparse
import json
import time
import urllib.request
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["baseline", "system"], required=True)
    p.add_argument("--model", default="qwen3.5:4b")
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    context = (root / "demo/README.md").read_text()
    messages = []
    if args.mode == "system":
        messages.append({"role": "system", "content": (root / "system.txt").read_text()})
    messages.append({"role": "user", "content": context + "\nКакая CI-система запускает тесты проекта?"})
    payload = {"model": args.model, "messages": messages, "stream": False, "think": False,
               "options": {"temperature": args.temperature, "seed": args.seed, "num_ctx": 4096, "num_predict": 512}}
    request = urllib.request.Request("http://localhost:11434/api/chat",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            answer = json.load(response)
    except Exception as exc:
        raise SystemExit("Local Ollama request failed: " + str(exc))
    duration = answer.get("eval_duration", 0)
    record = {"request": payload, "response": answer, "wall_seconds": time.perf_counter() - started,
              "load_seconds": answer.get("load_duration", 0) / 1e9,
              "total_seconds": answer.get("total_duration", 0) / 1e9,
              "decode_tokens_per_second": answer.get("eval_count", 0) / (duration / 1e9) if duration else None}
    with Path(args.output).open("x", encoding="utf-8") as out:
        json.dump(record, out, ensure_ascii=False, indent=2)
    print(answer.get("message", {}).get("content", ""))
    print("Saved:", args.output)

if __name__ == "__main__":
    main()

