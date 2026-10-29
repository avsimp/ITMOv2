"""Reproduce attacks over HTTP and save evidence; no external attack targets."""

import argparse
import importlib.util
import tempfile
import shutil
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from service import Shop, make_handler


class Fixture:
    def __enter__(self):
        self.shop = Shop()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.shop))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.records = []
        self.tokens = {}
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.shop.close()

    def call(self, label, method, path, body=None, headers=None):
        headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            text = response.read().decode()
            try:
                result = json.loads(text)
            except ValueError:
                result = text
            self.records.append({"label": label, "request": {"method": method, "path": path,
                                 "body": body, "headers": headers}, "status": response.status,
                                 "response": result})
            return response.status, result

    def login(self, user):
        _, response = self.call("login-" + user, "POST", "/login", {
            "username": user, "password": "learn-" + user,
        })
        self.tokens[response["token"]] = "<SESSION_" + user.upper() + ">"
        return {"X-Token": response["token"]}

    def save(self, path, data):
        text = json.dumps(data, ensure_ascii=False, indent=2)
        for token, placeholder in self.tokens.items():
            text = text.replace(token, placeholder)
        path.write_text(text + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--service", default=str(Path(__file__).with_name("service.py")))
    args = parser.parse_args()
    global Shop, make_handler
    spec = importlib.util.spec_from_file_location("audit_service", args.service)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    Shop, make_handler = module.Shop, module.make_handler
    out = Path(__file__).resolve().parent.parent / "evidence" / args.phase
    out.mkdir(parents=True, exist_ok=True)
    with Fixture() as f:
        alice = f.login("alice")
        f.login("bob")
        staff = f.login("staff")
        for label, method, path, body, auth in [
            ("V01-anonymous-profile", "GET", "/profile?id=1", None, {}),
            ("V02-foreign-profile", "GET", "/profile?id=2", None, alice),
            ("V02-orders", "GET", "/orders", None, alice),
            ("V02-foreign-context", "GET", "/assistant/context?order_id=2", None, alice),
            ("V03-profile-sql", "GET", "/profile?id=1%20OR%201=1", None, alice),
            ("V03-search-sql", "GET", "/search?q=%27%20OR%201=1--", None, alice),
            ("V03-context-sql", "GET", "/assistant/context?order_id=1%20OR%201=1", None, alice),
            ("V04-role-spoof", "GET", "/admin/export", None, {**alice, "X-Role": "staff"}),
            ("V05-price", "POST", "/orders", {"product": "chair", "price": -1}, alice),
            ("V06-foreign-file", "GET", "/files?user=bob", None, alice),
            ("V06-traversal", "GET", "/files?path=../../private/operator-note.txt", None, alice),
            ("V07-logs-customer", "GET", "/debug/logs", None, alice),
            ("V07-logs-staff", "GET", "/debug/logs", None, staff),
            ("V08-store-xss", "POST", "/reviews", {"product": "chair", "text": '<script>alert("TEST")</script>'}, alice),
            ("V08-view-xss", "GET", "/reviews/view", None, alice),
            ("V09-read-secret", "POST", "/assistant/execute", {"decision": {"tool": "read_file", "arguments": {"path": "private/operator-note.txt"}}}, alice),
            ("V09-export", "POST", "/assistant/execute", {"decision": {"tool": "export_profiles"}}, alice),
            ("V11-invalid-body", "POST", "/login", [], {}),
            ("V12-large-review", "POST", "/reviews", {"product": "chair", "text": "x" * 5000}, alice),
            ("V09-delete", "POST", "/assistant/execute", {"decision": {"tool": "delete_tree", "arguments": {"path": "."}}}, alice),
        ]:
            f.call(label, method, path, body, auth)
        f.save(out / "http-attacks.json", {
            "base_url": f.base, "service_sha256": hashlib.sha256(Path(args.service).read_bytes()).hexdigest(),
            "requests": f.records, "sandbox_exists_after_delete": f.shop.sandbox.root.exists(),
        })
    with tempfile.TemporaryDirectory(prefix="shop-tests-") as directory:
        for source in Path(__file__).parent.glob("*.py"):
            shutil.copy2(source, directory)
        shutil.copy2(args.service, Path(directory) / "service.py")
        tests = subprocess.run([sys.executable, "-B", "-m", "unittest", "-v"], cwd=directory,
                               capture_output=True, text=True)
    (out / "tests.txt").write_text(f"exit_code={tests.returncode}\n" + tests.stdout + tests.stderr)
    print(f"Evidence: {out}; tests exit={tests.returncode}")


if __name__ == "__main__":
    main()
