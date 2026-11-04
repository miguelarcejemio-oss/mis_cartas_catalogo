import unittest
from scripts.importar_mundial_2026 import parse


class ImportTests(unittest.TestCase):
    def test_counters_and_unicode(self):
        cards, report = parse('GOLDEN BALLERS\n1·1.- GB MESSI (ARG) 12\n·2.- VINÍ JÚNIOR 335\n')
        self.assertEqual([c['numero'] for c in cards], ['1', '2'])
        self.assertEqual(cards[1]['nombre'], 'VINÍ JÚNIOR')
        self.assertNotIn('cantidad', cards[0])

    def test_specials_without_invented_numbers(self):
        cards, _ = parse('LIMITADAS\n36 faltas\n1·XXL ARG MESSI 5387\nLimitadas Coin\n·EL COIN 150 13\n')
        self.assertEqual(len(cards), 2)
        self.assertIsNone(cards[0]['numero'])
        self.assertEqual(cards[1]['nombre'], 'EL COIN 150')
        self.assertEqual(cards[1]['seccion'], 'Limitadas Coin')

    def test_duplicates_conflicts_and_prefix(self):
        cards, report = parse('EQUIPO\n·1.- A 12\n·1.- A 12\n·1.- B 13\n·FTS2.- C 14\n')
        self.assertEqual(len(cards), 3)
        self.assertEqual(len(report['incidencias']), 1)
        self.assertEqual(len(report['numeros_con_nombres_distintos']), 1)
        self.assertEqual(cards[2]['numero'], 'FTS2')

    def test_missing_section_is_reported(self):
        cards, report = parse('·1.- A 12')
        self.assertEqual(cards, [])
        self.assertEqual(len(report['incidencias']), 1)

    def test_upgrade_codes_and_interface_text(self):
        cards, report = parse('UPGRADE\n·U01.- TAGLIAFICO (ARG) 863\nEDICIÓN LIMITADA\n·EL MESSI 304\nforward_to_inbox\n·EL RODRYGO 3771')
        self.assertEqual(cards[0]['numero'], 'U01')
        self.assertEqual(cards[2]['seccion'], 'EDICIÓN LIMITADA')
        self.assertEqual(report['secciones'], 2)


if __name__ == '__main__':
    unittest.main()
