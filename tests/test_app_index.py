import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.build_app_index import app_index, build_app_index, WORLD_CUP


class AppIndexTests(unittest.TestCase):
    def setUp(self):
        self.seed = {'collections': [
            {'id': WORLD_CUP, 'cards': [], 'card_count': 1,
             'public_checklist_file': 'checklists/old.json', 'bundled_checklist': True},
            {'id': 'other', 'cards': [], 'card_count': 20,
             'public_checklist_file': 'checklists/other.json'}]}
        self.catalog = {'collections': [{'id': WORLD_CUP,
            'cards': [{'id': 'stable-1', 'n': 1, 'player': 'Messi'},
                      {'id': 'stable-U01', 'n': 'U01', 'player': 'Tagliafico', 'section': 'UPGRADE'}]}]}

    def test_inline_update_preserves_other_catalogue_references(self):
        original = copy.deepcopy(self.seed)
        result = app_index(self.catalog, self.seed)
        self.assertEqual(result['collections'][1], original['collections'][1])
        fresh = result['collections'][0]
        self.assertEqual(fresh['card_count'], 2)
        self.assertEqual(fresh['cards'][0]['id'], 'stable-1')
        self.assertNotIn('public_checklist_file', fresh)
        self.assertNotIn('bundled_checklist', fresh)
        self.assertEqual(self.seed, original)
        self.assertEqual(app_index(self.catalog, result), result)

    def test_shrink_or_duplicate_ids_block_publication(self):
        self.seed['collections'][0]['card_count'] = 3
        with self.assertRaises(ValueError):
            app_index(self.catalog, self.seed)
        self.seed['collections'][0]['card_count'] = 1
        self.catalog['collections'][0]['cards'][1]['id'] = 'stable-1'
        with self.assertRaises(ValueError):
            app_index(self.catalog, self.seed)

    def test_build_emits_actual_apk_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'importaciones').mkdir()
            (root / 'importaciones/app_catalog_index_v125.json').write_text(json.dumps(self.seed))
            out = root / 'site'
            out.mkdir()
            build_app_index(root, out, self.catalog)
            result = json.loads((out / 'catalog-index.json').read_text())
            self.assertEqual(result['collections'][0]['cards'][1]['n'], 'U01')
