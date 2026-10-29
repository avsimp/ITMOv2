"""Security contracts: these tests must fail on the original exercise."""

import json
import unittest

from test_http import HttpTest as _HttpTest


class SecurityTest(_HttpTest):
    def login(self, username="alice"):
        status, _, text = self.call("POST", "/login", {
            "username": username, "password": "learn-" + username,
        })
        self.assertEqual(status, 200)
        return {"X-Token": json.loads(text)["token"]}

    def test_private_endpoints_require_session(self):
        for method, path, body in [
            ("GET", "/profile?id=1", None), ("GET", "/search?q=TEST", None),
            ("GET", "/orders", None), ("GET", "/files", None),
            ("GET", "/debug/logs", None), ("GET", "/assistant/context", None),
            ("GET", "/admin/export", None),
            ("POST", "/reviews", {"product": "chair", "text": "ok"}),
            ("POST", "/assistant/execute", {"decision": {"tool": "export_profiles"}}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, body)[0], 401)

    def test_owner_isolation(self):
        auth = self.login()
        self.assertEqual(self.call("GET", "/profile?id=2", headers=auth)[0], 403)
        status, _, text = self.call("GET", "/orders", headers=auth)
        self.assertEqual(status, 200)
        self.assertTrue(all(order["owner"] == 1 for order in json.loads(text)))
        self.assertEqual(self.call("GET", "/assistant/context?order_id=2", headers=auth)[0], 403)

    def test_sql_injection_rejected_or_treated_as_data(self):
        auth = self.login()
        for path in ("/profile?id=1%20OR%201=1", "/assistant/context?order_id=1%20OR%201=1"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path, headers=auth)[0], 400)
        status, _, text = self.call("GET", "/search?q=%27%20OR%201=1--", headers=auth)
        self.assertEqual((status, json.loads(text)), (200, []))

    def test_role_header_never_grants_privilege(self):
        auth = {**self.login(), "X-Role": "staff"}
        self.assertEqual(self.call("GET", "/admin/export", headers=auth)[0], 403)
        self.assertEqual(self.call("GET", "/admin/export", headers={"X-Role": "staff"})[0], 401)
        self.assertEqual(self.call("GET", "/admin/export", headers=self.login("staff"))[0], 200)

    def test_price_is_always_from_catalog(self):
        for price in (-1, 0, 0.01, "free", {"nested": True}):
            with self.subTest(price=price):
                status, _, text = self.call("POST", "/orders", {"product": "chair", "price": price}, self.login())
                self.assertEqual(status, 201)
                self.assertEqual(json.loads(text)["price"], 5000)

    def test_file_owner_and_canonical_path(self):
        auth = self.login()
        for path in (
            "/files?user=bob", "/files?path=../bob/receipt.txt",
            "/files?path=../../private/operator-note.txt",
            "/files?user=../private&path=operator-note.txt",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path, headers=auth)[0], 403)

    def test_logs_are_staff_only_and_redacted(self):
        auth = self.login()
        self.assertEqual(self.call("GET", "/debug/logs", headers=auth)[0], 403)
        status, _, text = self.call("GET", "/debug/logs", headers=self.login("staff"))
        self.assertEqual(status, 200)
        self.assertNotIn(auth["X-Token"], text)
        self.assertNotIn("learn-alice", text)
        self.assertNotIn('"headers"', text)

    def test_review_html_is_escaped(self):
        auth = self.login()
        payload = '<script>alert("TEST")</script>'
        self.assertEqual(self.call("POST", "/reviews", {"product": "chair", "text": payload}, auth)[0], 201)
        status, headers, text = self.call("GET", "/reviews/view")
        self.assertEqual(status, 200)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("Content-Security-Policy", headers)

    def test_executor_cannot_read_foreign_or_private_files(self):
        for user in ("alice", "staff"):
            for path in ("files/bob/receipt.txt", "private/operator-note.txt", "files/alice/../bob/receipt.txt"):
                with self.subTest(user=user, path=path):
                    self.assertEqual(self.call("POST", "/assistant/execute", {
                        "decision": {"tool": "read_file", "arguments": {"path": path}},
                    }, self.login(user))[0], 403)

    def test_executor_denies_export_and_delete_even_for_staff(self):
        for user in ("alice", "staff"):
            for tool, arguments in (("export_profiles", {}), ("delete_tree", {"path": "."})):
                with self.subTest(user=user, tool=tool):
                    self.assertEqual(self.call("POST", "/assistant/execute", {
                        "decision": {"tool": tool, "arguments": arguments},
                    }, self.login(user))[0], 403)
        self.assertTrue(self.shop.sandbox.root.exists())
        self.assertIn("TEST_ONLY", self.shop.sandbox.read("private/operator-note.txt"))

    def test_context_separates_untrusted_reviews_and_limits_tools(self):
        auth = self.login()
        status, _, text = self.call("GET", "/assistant/context?order_id=1", headers=auth)
        self.assertEqual(status, 200)
        context = json.loads(json.loads(text)["prompt"])
        self.assertEqual(context["allowed_tools"], ["read_file"])
        self.assertEqual(context["receipt_path"], "files/alice/receipt.txt")
        self.assertIn("untrusted_reviews", context)

    def test_bad_json_shapes_are_client_errors(self):
        auth = self.login()
        for path, body in (
            ("/login", []), ("/login", {"username": []}),
            ("/orders", {}), ("/orders", {"product": []}),
            ("/reviews", {"product": "chair", "text": []}),
            ("/assistant/execute", {}), ("/assistant/execute", {"decision": []}),
            ("/assistant/execute", {"decision": {"tool": "read_file", "arguments": []}}),
        ):
            with self.subTest(path=path, body=body):
                status, _, text = self.call("POST", path, body, auth)
                self.assertEqual(status, 400)
                self.assertNotIn('"type"', text)

    def test_raw_transport_errors_do_not_disclose_details(self):
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        for data in (b"{broken", b"\xff"):
            with self.subTest(data=data):
                request = Request(self.base + "/login", data=data, headers={"Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request, timeout=5)
                self.assertEqual(caught.exception.code, 400)
                self.assertNotIn(b'"type"', caught.exception.read())

    def test_oversized_review_and_query_rejected(self):
        auth = self.login()
        self.assertEqual(self.call("POST", "/reviews", {"product": "chair", "text": "x" * 5000}, auth)[0], 400)
        self.assertEqual(self.call("GET", "/search?q=" + "x" * 9000, headers=auth)[0], 414)


# Do not let unittest discover the imported base class a second time.
del _HttpTest

if __name__ == "__main__":
    unittest.main()
