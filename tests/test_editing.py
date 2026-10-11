import unittest

from yama.app import App
from yama.macros import Event, text_to_events


class PartnerTest(unittest.TestCase):
    def test_press_and_release_are_paired(self):
        events, _ = text_to_events("hola")  # h↓ h↑ o↓ o↑ ...
        self.assertEqual(App._partner(events, 0), 1)
        self.assertEqual(App._partner(events, 1), 0)
        self.assertEqual(App._partner(events, 4), 5)

    def test_shift_pairs_around_letter(self):
        events, _ = text_to_events("H")  # Shift↓ H↓ H↑ Shift↑
        self.assertEqual(App._partner(events, 0), 3)
        self.assertEqual(App._partner(events, 1), 2)

    def test_unmatched_release_has_no_partner(self):
        events = [Event(False, 0x04, False)]
        self.assertIsNone(App._partner(events, 0))


if __name__ == "__main__":
    unittest.main()
