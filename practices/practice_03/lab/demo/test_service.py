import unittest
from service import subscribe, subscribers, unsubscribe


class SubscribeTest(unittest.TestCase):
    def setUp(self):
        subscribers.clear()

    def test_subscribe(self):
        self.assertEqual(subscribe("Ann"), {"subscribed": True})
        self.assertEqual(subscribers, {"Ann"})

    def test_empty(self):
        with self.assertRaises(ValueError):
            subscribe(" ")

    def test_duplicate(self):
        subscribe("Ann")
        subscribe("Ann")
        self.assertEqual(len(subscribers), 1)


class UnsubscribeTest(unittest.TestCase):
    def setUp(self):
        subscribers.clear()

    def test_unsubscribe(self):
        subscribe("Ann")
        self.assertEqual(unsubscribe("Ann"), {"unsubscribed": True})
        self.assertEqual(subscribers, set())

    def test_unknown(self):
        subscribe("Ann")
        self.assertEqual(unsubscribe("Bob"), {"unsubscribed": False})
        self.assertEqual(subscribers, {"Ann"})

    def test_repeated(self):
        subscribe("Ann")
        self.assertEqual(unsubscribe("Ann"), {"unsubscribed": True})
        self.assertEqual(unsubscribe("Ann"), {"unsubscribed": False})
        self.assertEqual(subscribers, set())

    def test_whitespace(self):
        subscribe(" Ann ")
        self.assertEqual(unsubscribe("\tAnn \n"), {"unsubscribed": True})
        self.assertEqual(subscribers, set())

    def test_empty(self):
        subscribe("Ann")
        for name in ("", " ", "\t\n"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "^empty name$"):
                    unsubscribe(name)
                self.assertEqual(subscribers, {"Ann"})

    def test_case_sensitive(self):
        subscribe("Ann")
        self.assertEqual(unsubscribe("ann"), {"unsubscribed": False})
        self.assertEqual(subscribers, {"Ann"})
        subscribe("ann")
        self.assertEqual(unsubscribe("ann"), {"unsubscribed": True})
        self.assertEqual(subscribers, {"Ann"})

    def test_preserves_other_subscribers(self):
        subscribe("Ann")
        subscribe("Bob")
        self.assertEqual(unsubscribe("Ann"), {"unsubscribed": True})
        self.assertEqual(subscribers, {"Bob"})


if __name__ == "__main__":
    unittest.main()
