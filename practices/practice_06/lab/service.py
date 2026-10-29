"""Local shop with server-side authorization and a restricted assistant."""

import argparse
import hmac
import html
import json
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from sandbox import Sandbox

MAX_URI_LENGTH = 8192
MAX_BODY_LENGTH = 65536
MAX_REVIEW_LENGTH = 1024
MAX_QUESTION_LENGTH = 2000
MAX_SEARCH_LENGTH = 512
MAX_LOGS = 500

INTEGER_RE = re.compile(r"[0-9]{1,9}")


class Shop:
    def __init__(self):
        self.sandbox = Sandbox()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE profiles(id INTEGER PRIMARY KEY, name TEXT, email TEXT, address TEXT);
            INSERT INTO profiles VALUES
                (1, 'TEST_ALICE', 'alice@example.invalid', 'TEST_ADDRESS_A'),
                (2, 'TEST_BOB', 'bob@example.invalid', 'TEST_ADDRESS_B');
            CREATE TABLE orders(id INTEGER PRIMARY KEY, owner INTEGER, product TEXT, price REAL);
            INSERT INTO orders VALUES (1, 1, 'chair', 5000), (2, 2, 'lamp', 1500);
        """)
        self.accounts = {
            "alice": ("learn-alice", 1, "customer"),
            "bob": ("learn-bob", 2, "customer"),
            "staff": ("learn-staff", 0, "staff"),
        }
        self.user_names = {1: "alice", 2: "bob", 0: "staff"}
        self.sessions = {}
        self.products = {"chair": 5000, "lamp": 1500}
        self.reviews = []
        self.logs = []

    def rows(self, query, params=()):
        return [dict(row) for row in self.db.execute(query, params)]

    @staticmethod
    def integer(value):
        if not isinstance(value, str) or not INTEGER_RE.fullmatch(value):
            return None
        return int(value)

    def session(self, headers):
        token = headers.get("X-Token") if headers else None
        if not isinstance(token, str):
            return None
        return self.sessions.get(token)

    def authenticated(self, headers):
        session = self.session(headers)
        if session is None:
            return None, (401, {"error": "login required"})
        return session, None

    def receipt_path(self, session):
        username = self.user_names.get(session["id"])
        if not username or username == "staff":
            return None
        return f"files/{username}/receipt.txt"

    def dispatch(self, method, target, body, headers):
        if not isinstance(target, str):
            return 400, {"error": "invalid request"}
        if len(target) > MAX_URI_LENGTH:
            return 414, {"error": "uri too long"}
        url = urlsplit(target)
        query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        self.logs.append({"method": method, "path": url.path})
        if len(self.logs) > MAX_LOGS:
            del self.logs[:-MAX_LOGS]

        if method == "GET" and url.path == "/health":
            return 200, {"status": "ok"}
        if method == "GET" and url.path == "/products":
            return 200, self.products
        if method == "POST" and url.path == "/login":
            if not isinstance(body, dict):
                return 400, {"error": "invalid request"}
            username, password = body.get("username"), body.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                return 400, {"error": "invalid request"}
            account = self.accounts.get(username)
            if not account or not hmac.compare_digest(password.encode(), account[0].encode()):
                return 401, {"error": "invalid credentials"}
            token = secrets.token_hex(32)
            self.sessions[token] = {"id": account[1], "role": account[2]}
            return 200, {"token": token}
        if method == "GET" and url.path == "/profile":
            session, error = self.authenticated(headers)
            if error:
                return error
            profile_id = self.integer(query.get("id", str(session["id"])))
            if profile_id is None:
                return 400, {"error": "invalid id"}
            if session["role"] != "staff" and profile_id != session["id"]:
                return 403, {"error": "forbidden"}
            return 200, self.rows("SELECT * FROM profiles WHERE id = ?", (profile_id,))
        if method == "GET" and url.path == "/search":
            session, error = self.authenticated(headers)
            if error:
                return error
            needle = query.get("q", "")
            if len(needle) > MAX_SEARCH_LENGTH:
                return 414, {"error": "query too long"}
            pattern = f"%{needle}%"
            if session["role"] == "staff":
                return 200, self.rows("SELECT * FROM profiles WHERE name LIKE ?", (pattern,))
            return 200, self.rows("SELECT * FROM profiles WHERE name LIKE ? AND id = ?",
                                  (pattern, session["id"]))
        if method == "GET" and url.path == "/orders":
            session, error = self.authenticated(headers)
            if error:
                return error
            if session["role"] == "staff":
                return 200, self.rows("SELECT * FROM orders")
            return 200, self.rows("SELECT * FROM orders WHERE owner = ?", (session["id"],))
        if method == "POST" and url.path == "/orders":
            session, error = self.authenticated(headers)
            if error:
                return error
            if not isinstance(body, dict):
                return 400, {"error": "invalid request"}
            product = body.get("product")
            if not isinstance(product, str) or product not in self.products:
                return 400, {"error": "unknown product"}
            price = self.products[product]
            cursor = self.db.execute("INSERT INTO orders(owner, product, price) VALUES (?, ?, ?)",
                                     (session["id"], product, price))
            self.db.commit()
            return 201, {"id": cursor.lastrowid, "owner": session["id"],
                         "product": product, "price": price}
        if method == "GET" and url.path == "/admin/export":
            session, error = self.authenticated(headers)
            if error:
                return error
            if session["role"] != "staff":
                return 403, {"error": "staff only"}
            return 200, self.rows("SELECT * FROM profiles")
        if method == "GET" and url.path == "/files":
            session, error = self.authenticated(headers)
            if error:
                return error
            username = self.user_names.get(session["id"])
            if session["role"] != "customer" or username is None:
                return 403, {"error": "forbidden"}
            if query.get("user", username) != username:
                return 403, {"error": "forbidden"}
            if query.get("path", "receipt.txt") != "receipt.txt":
                return 403, {"error": "forbidden"}
            try:
                content = self.sandbox.read(f"files/{username}/receipt.txt")
            except (ValueError, OSError):
                return 403, {"error": "forbidden"}
            return 200, {"content": content}
        if method == "GET" and url.path == "/debug/logs":
            session, error = self.authenticated(headers)
            if error:
                return error
            if session["role"] != "staff":
                return 403, {"error": "staff only"}
            return 200, self.logs.copy()
        if method == "POST" and url.path == "/reviews":
            session, error = self.authenticated(headers)
            if error:
                return error
            if not isinstance(body, dict):
                return 400, {"error": "invalid request"}
            product, text = body.get("product"), body.get("text")
            if not isinstance(product, str) or product not in self.products:
                return 400, {"error": "unknown product"}
            if not isinstance(text, str) or len(text) > MAX_REVIEW_LENGTH:
                return 400, {"error": "invalid review"}
            self.reviews.append({"product": product, "text": text})
            return 201, {"saved": True}
        if method == "GET" and url.path == "/reviews/view":
            rendered = "".join(f"<p>{html.escape(review['text'], quote=True)}</p>"
                               for review in self.reviews)
            return 200, "<html><body>" + rendered + "</body></html>"
        if method == "GET" and url.path == "/assistant/context":
            session, error = self.authenticated(headers)
            if error:
                return error
            order_id = self.integer(query.get("order_id", "1"))
            if order_id is None:
                return 400, {"error": "invalid order"}
            orders = self.rows("SELECT * FROM orders WHERE id = ?", (order_id,))
            if not orders:
                return 404, {"error": "order not found"}
            order = orders[0]
            if session["role"] != "staff" and order["owner"] != session["id"]:
                return 403, {"error": "forbidden"}
            receipt_path = self.receipt_path(session)
            if receipt_path is None:
                return 403, {"error": "forbidden"}
            question = query.get("question", "Покажи чек по заказу")
            if len(question) > MAX_QUESTION_LENGTH:
                return 400, {"error": "question too long"}
            context = {
                "order": order,
                "receipt_path": receipt_path,
                "allowed_tools": ["read_file"],
                "untrusted_reviews": self.reviews,
                "user_question": question,
            }
            return 200, {"prompt": json.dumps(context, ensure_ascii=False)}
        if method == "POST" and url.path == "/assistant/execute":
            session, error = self.authenticated(headers)
            if error:
                return error
            if not isinstance(body, dict):
                return 400, {"error": "invalid request"}
            decision = body.get("decision")
            if not isinstance(decision, dict):
                return 400, {"error": "invalid decision"}
            tool = decision.get("tool")
            arguments = decision.get("arguments", {})
            if not isinstance(tool, str) or not isinstance(arguments, dict):
                return 400, {"error": "invalid decision"}
            if tool == "read_file":
                path = arguments.get("path")
                if not isinstance(path, str):
                    return 400, {"error": "invalid arguments"}
                expected = self.receipt_path(session)
                if expected is None or path != expected:
                    return 403, {"error": "forbidden"}
                try:
                    content = self.sandbox.read(path)
                except (ValueError, OSError):
                    return 403, {"error": "forbidden"}
                return 200, {"content": content}
            if tool in ("export_profiles", "delete_tree"):
                return 403, {"error": "forbidden"}
            return 400, {"error": "unknown tool"}
        return 404, {"error": "not found"}

    def close(self):
        self.db.close()
        self.sandbox.close()


def make_handler(shop):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MiniShop"
        sys_version = ""

        def send_result(self, status, result):
            html_result = isinstance(result, str)
            data = (result if html_result else json.dumps(result, ensure_ascii=False)).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html_result
                             else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def handle_request(self):
            try:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_result(400, {"error": "invalid request"})
                    return
                if not 0 <= size <= MAX_BODY_LENGTH:
                    self.send_result(413, {"error": "payload too large"})
                    return
                raw = self.rfile.read(size) if size else b""
                if raw:
                    try:
                        body = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        self.send_result(400, {"error": "invalid json"})
                        return
                else:
                    body = {}
                with shop.lock:
                    status, result = shop.dispatch(self.command, self.path, body, self.headers)
            except Exception:
                status, result = 500, {"error": "internal error"}
            self.send_result(status, result)

        do_GET = do_POST = handle_request

        def log_message(self, format, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8066)
    args = parser.parse_args()
    shop = Shop()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(shop))
    server.daemon_threads = True
    print(f"Local exercise: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Disposable fixture files: {shop.sandbox.root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        shop.close()


if __name__ == "__main__":
    main()
