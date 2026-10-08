import json
import tempfile
import unittest
from pathlib import Path
from scripts.build_site import build

class PublicationTests(unittest.TestCase):
    def setup_site(self, root, cards=None, verification=None):
        cards=cards or [{'id':'existing','have':True,'status':'Falta'}]
        collection={'id':'test','cards':cards,'card_count':len(cards)}
        if verification is not None:
            collection['verification']=verification
        (root/'catalogo.json').write_text(json.dumps({'collections':[collection]}))
        for name in ('index.html','servidor.config.json','manifest.json'):
            (root/name).write_text('{}')
        (root/'portadas').mkdir()
        (root/'portadas'/'enriquecimiento.json').write_text('private report')
        (root/'portadas'/'existing.png').write_bytes(b'existing asset')
    def test_publication_catalog_identical_and_reports_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_site(root)
            out=build(root)
            self.assertEqual((out/'catalogo.json').read_bytes(),(root/'catalogo.json').read_bytes())
            self.assertTrue((out/'portadas'/'existing.png').exists())
            self.assertFalse((out/'portadas'/'enriquecimiento.json').exists())
    def test_incomplete_new_checklist_cannot_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_site(root,verification={'complete':True,'required_card_count':692})
            with self.assertRaisesRegex(ValueError,'cannot_deploy'):
                build(root)
    def test_duplicate_card_ids_cannot_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_site(root,cards=[{'id':'same'},{'id':'same'}])
            with self.assertRaisesRegex(ValueError,'duplicate'):
                build(root)
