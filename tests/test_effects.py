import unittest

from yama import device, layout
from yama.effects import CUSTOM, EFFECTS, Preview


class PreviewTest(unittest.TestCase):
    def test_every_effect_renders_valid_colors(self):
        custom = [(10, 20, 30)] * device.LED_COUNT
        for eff in EFFECTS:
            preview = Preview()
            for t in (0.0, 0.7, 3.1, 9.4):
                for random_on in (False, True):
                    frame = preview.frame(t, eff.code, (255, 0, 0), random_on, 3, 0, 4, custom)
                    self.assertEqual(len(frame), len(layout.KEYS), eff.name)
                    for rgb in frame:
                        self.assertTrue(all(0 <= v <= 255 for v in rgb), (eff.name, rgb))

    def test_brightness_zero_is_dark(self):
        frame = Preview().frame(1.0, 0x06, (255, 255, 255), False, 3, 0, 0, None)
        self.assertTrue(all(rgb == (0, 0, 0) for rgb in frame))

    def test_custom_uses_painted_colors(self):
        custom = [(0, 0, 0)] * device.LED_COUNT
        custom[0] = (1, 2, 3)  # Esc
        frame = Preview().frame(0, CUSTOM, (0, 0, 0), False, 3, 0, 4, custom)
        self.assertEqual(frame[0], (1, 2, 3))


class GroupsTest(unittest.TestCase):
    def test_groups_only_use_real_leds(self):
        real = set(layout.ALL_LEDS)
        for name, leds in layout.GROUPS.items():
            self.assertTrue(set(leds) <= real, name)


if __name__ == "__main__":
    unittest.main()
