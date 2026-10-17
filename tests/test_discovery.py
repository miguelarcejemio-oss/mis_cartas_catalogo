import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import collection_discovery as discovery
from scripts.catalog_health import health

class DiscoveryTests(unittest.TestCase):
    def test_recent_feed_detects_collection_missing_from_popular_table(self):
        page='<b>1</b><a href="https://cromosrepes.com/coleccion/ficha/FIFA-365-2027">Adrenalyn XL FIFA 365 2027</a><a href="/usuario/Miguel">Private profile</a>'
        rows=discovery.parse_recent(page,'https://cromosrepes.com/ranking/colecciones_nuevas',{'name':'recent'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],'Adrenalyn XL FIFA 365 2027')
        self.assertEqual(rows[0]['year'],'') # Edition number is not release year.
        self.assertEqual(rows[0]['checklist_status'],'not_verified')

    def test_empty_http_200_is_failure_and_does_not_refresh_old_last_seen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'portadas').mkdir()
            (root/'fuentes.json').write_text(json.dumps({'discovery_sources':[{'name':'index','type':'catalog_index','url':'https://example.org'}]}))
            (root/'catalogo.json').write_text('{"collections":[]}')
            prior={'identity_key':'old','name':'Old','year':'2025','publisher':'Other','detail_url':'https://example.org/old','first_seen':'2025-01-01','last_seen':'2025-02-01'}
            snapshot=root/'portadas/discovery_snapshot.json'
            snapshot.write_text(json.dumps({'collections':[prior]}))
            with patch.multiple(discovery,CATALOG=root/'catalogo.json',SOURCES=root/'fuentes.json',SNAPSHOT=snapshot,REPORT=root/'portadas/descubrimiento.json'),patch.object(discovery,'fetch',return_value=('<html>Login</html>','https://example.org')):
                self.assertEqual(discovery.run(),1)
            self.assertEqual(json.loads(snapshot.read_text())['collections'][0]['last_seen'],'2025-02-01')
            report=json.loads((root/'portadas/descubrimiento.json').read_text())
            self.assertEqual(len(report['errors']),1)

    def test_green_fetch_does_not_mean_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'portadas').mkdir()
            (root/'catalogo.json').write_text('{"version":18,"collections":[]}')
            (root/'portadas/descubrimiento.json').write_text(json.dumps({'checked_sources':[{'type':'recent_collections','status':'ok'}]}))
            (root/'portadas/enriquecimiento.json').write_text(json.dumps({'published':[],'pending_review':[{'name':'FIFA 365','blockers':[{'code':'checklist_not_public','url':'private proof not exported'}]}]}))
            status=health(root)
            self.assertEqual(status['status'],'pending_verification')
            self.assertEqual(status['published_this_run'],0)
            self.assertEqual(status['pending_verification'],1)
            self.assertNotIn('private proof',json.dumps(status))

if __name__=='__main__':
    unittest.main()
