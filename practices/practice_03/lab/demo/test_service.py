import unittest

from service import list_subscribers, subscribe, subscribers, unsubscribe


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


class ListSubscribersTest(unittest.TestCase):
    def setUp(self):
        subscribers.clear()

    def test_empty(self):
        self.assertEqual(list_subscribers(), [])

    def test_sorted_unique_normalized_names(self):
        for name in ("bob", " Ann ", "Bob", "ann", "Ann"):
            subscribe(name)
        self.assertEqual(list_subscribers(), ["Ann", "Bob", "ann", "bob"])
        self.assertEqual(subscribers, {"Ann", "Bob", "ann", "bob"})

    def test_result_mutation_does_not_change_subscriptions(self):
        subscribe("Ann")
        snapshot = list_subscribers()
        snapshot.clear()
        snapshot.append("Bob")
        self.assertEqual(subscribers, {"Ann"})
        self.assertEqual(list_subscribers(), ["Ann"])

    def test_snapshot_and_current_state_after_changes(self):
        subscribe("Ann")
        snapshot = list_subscribers()
        subscribe("Bob")
        self.assertEqual(list_subscribers(), ["Ann", "Bob"])
        unsubscribe("Ann")
        self.assertEqual(list_subscribers(), ["Bob"])
        self.assertEqual(snapshot, ["Ann"])
        unsubscribe("Bob")
        self.assertEqual(list_subscribers(), [])

    def test_repeated_reads_are_independent(self):
        subscribe("Ann")
        first = list_subscribers()
        second = list_subscribers()
        self.assertEqual(first, second)
        first.append("Bob")
        self.assertEqual(second, ["Ann"])
        self.assertEqual(subscribers, {"Ann"})


if __name__ == "__main__":
    unittest.main()
