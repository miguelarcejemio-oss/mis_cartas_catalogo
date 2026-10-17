import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.curated_checklists import cards_with_ids,publish,refresh
from scripts.public_checklists import row,laststicker_text,monopoly_text,validate
from scripts.discovery_public import run,metadata,sitemap_urls,PUBLIC

ROOT=Path(__file__).resolve().parents[1]

class ExpandedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'checklists-publicas.json').read_text())
        self.target=copy.deepcopy(self.data['collections'][0])

    def test_twelve_checklists_are_real_unique_records_with_explicit_scope(self):
        expected=[72,430,80,216,196,18,192,446,448,141,220,559]
        self.assertGreaterEqual(len(self.data['collections']),12)
        for target,minimum in zip(self.data['collections'],expected):
            self.assertGreaterEqual(len(target['cards']),minimum)
        all_ids=[]
        for t in self.data['collections']:
            validate(t['cards']);self.assertTrue(t['source_url'].startswith('https://'))
            self.assertTrue(t['scope']);self.assertTrue(t['evidence'])
            cards=cards_with_ids(t,t['cards']);all_ids.extend(c['id'] for c in cards)
            self.assertFalse(any(c.get('have') or c.get('qty') for c in cards))
        self.assertEqual(len(all_ids),len(set(all_ids)))

    def test_append_retains_identifiers_and_rejects_removal_or_reused_number(self):
        catalog={'collections':[]};t=self.target
        self.assertTrue(publish(catalog,t,t['cards'],'now'))
        old=copy.deepcopy(catalog['collections'][0]);ids=[c['id'] for c in old['cards']]
        self.assertFalse(publish(catalog,t,t['cards'],'later'))
        bigger=t['cards']+[row('EX-NEW','Nueva edición limitada','Extras')]
        self.assertTrue(publish(catalog,t,bigger,'later'))
        self.assertEqual([c['id'] for c in catalog['collections'][0]['cards']][:-1],ids)
        with self.assertRaisesRegex(ValueError,'removed_existing'):
            publish(catalog,t,t['cards'],'later')
        changed=copy.deepcopy(bigger);changed[0]['player']='Otro jugador'
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            publish(catalog,t,changed,'later')

    def test_outage_retains_snapshot_without_claiming_freshness(self):
        class Offline:
            def fetch(self,url):raise ValueError('HTTP 403')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'checklists-publicas.json').write_text(json.dumps({'collections':[self.target]}))
            catalog={'collections':[]};checks,updates=refresh(root,catalog,Offline())
            self.assertEqual(updates,[self.target['id']]);self.assertEqual(len(catalog['collections'][0]['cards']),len(self.target['cards']))
            self.assertEqual(checks[0]['status'],'reviewed_snapshot_retained');self.assertTrue(checks[0]['blockers'])

    def test_unnumbered_figures_and_printed_signatures_are_preserved(self):
        figures=self.data['collections'][5]['cards'];self.assertGreaterEqual(len(figures),18)
        self.assertTrue(all(c['n'] is None and c['original_identifier'] is None for c in figures))
        extra=self.data['collections'][7]['cards']
        self.assertGreaterEqual(sum(c['section']=='Facsimile Signature Style Pro View' for c in extra),5)
        self.assertFalse(any('Genuine Autograph' in c['section'] or 'Pro-View Original' in c['section'] for c in extra))
        self.assertGreaterEqual(sum(len(c['parallels']) for c in self.data['collections'][3]['cards']),200)

    def test_source_statistics_and_tba_are_not_cards(self):
        cards=laststicker_text('1 Cromo 1 - foil 69 125 23 0.55')
        self.assertEqual(cards[0]['player'],'Cromo 1');self.assertNotIn('125',json.dumps(cards))
        # A count without individual records cannot become a checklist.
        with self.assertRaisesRegex(ValueError,'missing_individual'):
            laststicker_text('220 cromos en total')

class PublicDiscoveryTests(unittest.TestCase):
    source={'name':'public','url':PUBLIC+'colecciones','publishers_url':PUBLIC+'editorial',
        'sitemap_url':'https://cromosrepes.com/sitemap-col.txt','publisher_budget':1,'detail_budget':1,'result_limit':1}

    def test_unknown_publication_year_keeps_collection_without_inventing_year(self):
        item=metadata({'nombre':'Antigua','escNombre':'ANTIGUA','editorialId':97,'anoPublica':None},
            {97:'Editorial desconocida hasta hoy'},self.source)
        self.assertEqual(item['year'],'');self.assertEqual(item['metadata_status'],'publication_year_pending')

    def test_new_manufacturer_is_discovered_without_allowlist_and_private_fields_are_removed(self):
        source=self.source
        class Client:
            def fetch(self,url):
                if url.endswith('/editorial'):data=[{'id':917,'nombre':'Fabricante nuevo','url':'private extra'}]
                elif url.endswith('sitemap-col.txt'):
                    return url,'text/plain',b'https://cromosrepes.com/coleccion/cromos/HISTORICA\nhttps://cromosrepes.com/coleccion/cromos/EVENTO-DE-INTERCAMBIO\n'
                else:data=[{'nombre':'Nueva','escNombre':'NUEVA','anoPublica':2026,'editorialId':917,'tipoId':1,'creadorNick':'private-name'}]
                if '/coleccion/HISTORICA' in url:data={'nombre':'Historica','escNombre':'HISTORICA','anoPublica':2000,'editorialId':917}
                return url,'application/json',json.dumps(data).encode()
        rows,report,state=run(source,{},[],Client())
        self.assertEqual(report['manufacturers_found'],1);self.assertTrue(report['capped_queries'])
        self.assertTrue(any(r['publisher']=='Fabricante nuevo' for r in rows))
        self.assertNotIn('creadorNick',json.dumps(rows));self.assertNotIn('private-name',json.dumps(rows))
        self.assertFalse(any('EVENTO' in u for u in state['sitemap_urls']))

    def test_failed_detail_is_requeued_and_registry_cursor_rotates(self):
        class Client:
            def fetch(self,url):
                if url.endswith('/editorial'):data=[{'id':1,'nombre':'A'},{'id':2,'nombre':'B'}]
                elif url.endswith('sitemap-col.txt'):raise ValueError('offline map')
                elif '/coleccion/' in url:raise ValueError('offline detail')
                else:data=[{'nombre':'Nueva','escNombre':'NUEVA','anoPublica':2026,'editorialId':2}]
                return url,'json',json.dumps(data).encode()
        url='https://cromosrepes.com/coleccion/cromos/PENDIENTE'
        _,report,state=run(self.source,{'url_backlog':[url],'publisher_cursor':0},[],Client())
        self.assertEqual(state['publisher_cursor'],1);self.assertIn(url,state['url_backlog']);self.assertTrue(report['errors'])

if __name__=='__main__':unittest.main()
