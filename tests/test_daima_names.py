import copy
import json
import unittest
from pathlib import Path
from scripts.integrar_daima_nombres import integrate, COLLECTION
from scripts.build_app_index import app_index
from scripts.curated_checklists import cards_with_ids, publish

ROOT = Path(__file__).resolve().parents[1]


class DaimaNamesTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads((ROOT / 'importaciones/dragon_ball_daima_nombres.json').read_text())
        self.cards = [{'id': r['id'], 'n': r['n'], 'player': r['previous_name'],
                       'section': 'Base', 'owned': r['n'] == 1,
                       'parallels': [{'id': 'parallel-original', 'name': 'Crystal Shard'}] if r['n'] <= 100 else []}
                      for r in self.snapshot['cards']]
        self.cards += [{'id': 'original-limited-' + str(n), 'n': 'LE ' + str(n), 'player': 'Limitada ' + str(n)} for n in range(1, 10)]
        self.original = {'collections': [{'id': COLLECTION, 'name': 'Daima', 'cards': self.cards},
                                          {'id': 'other', 'cards': [], 'owned': True}]}

    def test_names_marks_variants_limits_other_collections_and_idempotence(self):
        result = integrate(self.original, self.snapshot)
        fresh = result['collections'][0]
        self.assertEqual(len(fresh['cards']), 216)
        self.assertEqual(fresh['cards'][0]['player'], 'Son Goku')
        self.assertEqual(fresh['cards'][135]['player'], 'Episodio 1')
        self.assertEqual(fresh['cards'][136]['player'], 'Episodio 1 · momento destacado 1')
        self.assertEqual(fresh['cards'][198]['player'], 'Son Goku')
        for old, new in zip(self.cards, fresh['cards']):
            self.assertEqual(old['id'], new['id'])
            self.assertEqual(old['n'], new['n'])
            self.assertEqual(old.get('parallels'), new.get('parallels'))
            self.assertEqual(old.get('owned'), new.get('owned'))
        self.assertEqual(fresh['cards'][-9:], self.cards[-9:])
        self.assertEqual(result['collections'][1], self.original['collections'][1])
        self.assertEqual(integrate(result, self.snapshot), result)
        self.assertEqual(self.original['collections'][0]['cards'][0]['player'], 'Card 1')

    def test_identity_conflict_blocks_without_mutating_original(self):
        before = copy.deepcopy(self.original)
        self.original['collections'][0]['cards'][0]['n'] = 999
        with self.assertRaises(ValueError):
            integrate(self.original, self.snapshot)
        self.assertEqual(self.original['collections'][0]['cards'][0]['player'], 'Card 1')
        self.original = before
        self.original['collections'][0]['cards'][0]['player'] = 'Different person'
        with self.assertRaises(ValueError):
            integrate(self.original, self.snapshot)

    def test_missing_number_blocks(self):
        self.snapshot['cards'].pop()
        with self.assertRaises(ValueError):
            integrate(self.original, self.snapshot)

    def test_installed_apk_gets_inline_names_instead_of_old_numeric_shard(self):
        seed = {'collections': [{'id': COLLECTION, 'cards': [], 'card_count': 216,
                'public_checklist_file': 'checklists/old-numeric.json', 'bundled_checklist': True},
                {'id': 'unrelated', 'cards': [], 'card_count': 7}]}
        result = app_index(integrate(self.original, self.snapshot), seed)
        entry = result['collections'][0]
        self.assertEqual(entry['cards'][0]['player'], 'Son Goku')
        self.assertNotIn('public_checklist_file', entry)
        self.assertNotIn('bundled_checklist', entry)
        self.assertEqual(result['collections'][1], seed['collections'][1])

    def test_automatic_numeric_source_refresh_keeps_reviewed_titles(self):
        target=next(c for c in json.loads((ROOT/'checklists-publicas.json').read_text())['collections'] if c['id']==COLLECTION)
        catalog={'collections':[{'id':COLLECTION,'cards':cards_with_ids(target,target['cards'])}]}
        named=integrate(catalog,self.snapshot)
        self.assertFalse(publish(named,target,target['cards'],'2026-11-08'))
        self.assertEqual(named['collections'][0]['cards'][0]['player'],'Son Goku')
        changed=copy.deepcopy(target['cards'])
        changed[0]['player']='Different person'
        with self.assertRaises(ValueError):
            publish(named,target,changed,'2026-11-08')
