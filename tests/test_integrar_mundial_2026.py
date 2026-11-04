import unittest
from scripts.integrar_mundial_2026 import integrate, COLLECTION


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'numero': str(n), 'nombre': 'Jugador ' + str(n), 'seccion': 'MÉJICO'} for n in range(1, 649)]
        self.catalog = {'collections': [
            {'id': COLLECTION, 'cards': [{'id': 'id-personal-1', 'n': 1,
                'player': 'Jugador 1 45', 'section': 'MÉJICO', 'team': 'MÉJICO', 'owned': True}]},
            {'id': 'otra', 'cards': [], 'metadata': 'conservar'}]}

    def test_preserves_marks_ids_other_collections_and_is_idempotent(self):
        result = integrate(self.catalog, self.rows)
        card = result['collections'][0]['cards'][0]
        self.assertEqual(card['id'], 'id-personal-1')
        self.assertTrue(card['owned'])
        self.assertEqual(card['team'], 'MÉXICO')
        self.assertEqual(result['collections'][1], self.catalog['collections'][1])
        self.assertEqual(integrate(result, self.rows), result)
        self.assertEqual(self.catalog['collections'][0]['cards'][0]['player'], 'Jugador 1 45')

    def test_identity_change_is_blocked(self):
        self.rows[0]['nombre'] = 'Otra persona'
        with self.assertRaises(ValueError):
            integrate(self.catalog, self.rows)

    def test_missing_base_is_blocked(self):
        with self.assertRaises(ValueError):
            integrate(self.catalog, self.rows[:-1])

    def test_unnumbered_variants_not_published(self):
        result = integrate(self.catalog, self.rows + [{'numero': None, 'nombre': 'Especial', 'seccion': 'LIMITADAS'}])
        self.assertEqual(len(result['collections'][0]['cards']), 648)


if __name__ == '__main__':
    unittest.main()
