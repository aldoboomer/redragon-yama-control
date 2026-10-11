import unittest

from yama.layout import G_KEY_INDEX, g_default_entry
from yama.macros import Event, Macro, decode_blob, encode_blob

# Macro "1" que escribe "hola", con el formato exacto del programa oficial de
# Redragon: esperas de 50 ms, el último evento sin espera y basura en el byte 8.
REDRAGON_BLOB = bytes.fromhex(
    "aa 55 38 00 01 00 01 00 2b 00 00 00 00 00 00 00 12 00 08 00 01 01 05 a0 02 0b 05 20 02 0b"
    " 05 a0 02 12 05 20 02 12 05 a0 02 0f 05 20 02 0f 05 a0 02 04 00 20 02 04 31 00"
)


class MacroBlobTest(unittest.TestCase):
    def test_decodes_redragon_blob(self):
        (m,) = decode_blob(REDRAGON_BLOB)
        self.assertEqual(m.name, "1")
        self.assertEqual(len(m.events), 8)
        first = m.events[0]
        self.assertEqual((first.is_modifier, first.code, first.down, first.delay_ms), (False, 0x0B, True, 50))
        self.assertFalse(m.events[-1].down)

    def test_reencodes_same_body(self):
        macros = decode_blob(REDRAGON_BLOB)
        out = encode_blob(macros)
        # el byte 8 del original es basura de memoria sin inicializar del programa oficial
        self.assertEqual(out[:8], REDRAGON_BLOB[:8])
        self.assertEqual(out[0x10:], REDRAGON_BLOB[0x10:])

    def test_roundtrip_two_macros(self):
        macros = [
            Macro("hola", [Event(False, 0x0B, True), Event(False, 0x0B, False)], repeat=3),
            Macro("ctrl+c", [Event(True, 0x01, True, 0), Event(False, 0x06, True), Event(False, 0x06, False),
                             Event(True, 0x01, False)]),
        ]
        back = decode_blob(encode_blob(macros))
        self.assertEqual([(m.name, m.repeat, len(m.events)) for m in back], [("hola", 3, 2), ("ctrl+c", 1, 4)])
        self.assertTrue(back[1].events[0].is_modifier)

    def test_without_names_is_smaller_and_readable(self):
        macros = [Macro("un nombre largo", [Event(False, 0x04, True), Event(False, 0x04, False)])]
        full, short = encode_blob(macros), encode_blob(macros, names=False)
        self.assertEqual(len(full) - len(short), 2 * len("un nombre largo"))
        (back,) = decode_blob(short)
        self.assertEqual((back.name, len(back.events)), ("Macro 1", 2))


class LayoutTest(unittest.TestCase):
    def test_g_keys_match_factory_keymap(self):
        # posiciones y códigos leídos del teclado: G1 en 7 (06 12 12), G2 en 23 (06 13 13)
        self.assertEqual(G_KEY_INDEX[1], 7)
        self.assertEqual(G_KEY_INDEX[2], 23)
        self.assertEqual(G_KEY_INDEX[7], 15)
        self.assertEqual(g_default_entry(1), bytes((6, 0x12, 0x12)))
        self.assertEqual(g_default_entry(12), bytes((6, 0x1D, 0x1D)))


if __name__ == "__main__":
    unittest.main()
