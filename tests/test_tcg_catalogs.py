import copy
import json
import tempfile
import unittest
from pathlib import Path
from scripts.tcg_catalogs import ygo_collections,ygo_id,one_piece_registry,one_piece_collection,publish,refresh

class TcgCatalogTests(unittest.TestCase):
    def sample(self):
        sets=[{'set_name':'A','set_code':'XYZ','num_of_cards':1,'tcg_date':'2001-01-01'}]
        card={'id':12,'name':'Real card','type':'Monster','card_sets':[
            {'set_name':'A','set_code':'XYZ-E001','set_rarity':'Common'},
            {'set_name':'A','set_code':'XYZ-EN001','set_rarity':'Quarter Century Secret Rare'}]}
        return sets,{'data':[card]}

    def test_regional_printings_group_without_invented_numbers(self):
        sets,payload=self.sample();rows,pending=ygo_collections(sets,payload)
        self.assertFalse(pending);self.assertEqual(len(rows[0]['cards']),1)
        c=rows[0]['cards'][0];self.assertEqual(c['n'],'XYZ-EN001')
        self.assertEqual(len(c['parallels']),2)
        payload['data'][0]['card_sets'].reverse()
        self.assertEqual(rows,ygo_collections(sets,payload)[0])

    def test_reused_product_code_does_not_collide(self):
        sets,_=self.sample();other={**sets[0],'set_name':'Different product'}
        self.assertNotEqual(ygo_id(sets[0]),ygo_id(other))

    def test_incomplete_and_future_sources_do_not_publish(self):
        sets,payload=self.sample();sets[0]['num_of_cards']=2
        self.assertFalse(ygo_collections(sets,payload)[0])
        sets[0].update(num_of_cards=1,tcg_date='2999-01-01')
        self.assertFalse(ygo_collections(sets,payload)[0])

    def test_updater_is_idempotent_and_rejects_removal_or_identity_reuse(self):
        sets,payload=self.sample();c=ygo_collections(sets,payload)[0][0];catalog={'collections':[]}
        self.assertTrue(publish(catalog,c,'now'));before=copy.deepcopy(catalog)
        self.assertFalse(publish(catalog,c,'later'));self.assertEqual(catalog,before)
        changed=copy.deepcopy(c);changed['cards']=[]
        with self.assertRaisesRegex(ValueError,'removed'):publish(catalog,changed,'later')
        changed=copy.deepcopy(c);changed['cards'][0]['player']='Different card'
        with self.assertRaisesRegex(ValueError,'identity'):publish(catalog,changed,'later')
        changed=copy.deepcopy(c);changed['cards'][0]['parallels']=[]
        with self.assertRaisesRegex(ValueError,'variants'):publish(catalog,changed,'later')
        self.assertEqual(catalog,before)

    def test_one_piece_registry_selects_only_real_booster_options(self):
        raw='<select name="series"><option value="569101">Booster [OP-01]</option><option value="42">Deck [ST-01]</option></select>'
        self.assertEqual(one_piece_registry(raw),[{'id':'OP-01','series':'569101','name':'Booster [OP-01]'}])

    def test_one_piece_grouped_by_printed_number_not_image_suffix(self):
        raw=''.join(f'<dl class="modalCol" id="OP01-{i:03d}"><dt><div class="infoCol"><span>OP01-{i:03d}</span><span>C</span><span>CHARACTER</span></div><div class="cardName">Card {i}</div></dt></dl>' for i in range(1,21))
        raw+=raw[:raw.index('</dl>')+5].replace('id="OP01-001"','id="OP01-001_p1"')
        c=one_piece_collection({'id':'OP-01','series':'569101','name':'REAL<br> NAME'},raw)
        self.assertEqual(len(c['cards']),20);self.assertNotIn('<br>',c['name'])
        self.assertEqual(c['cards'][0]['n'],'OP01-001');self.assertNotIn('parallels',c['cards'][0])
        with self.assertRaisesRegex(ValueError,'truncated'):one_piece_collection({'id':'OP-01'},'<html>Loading</html>')

    def test_outage_keeps_every_saved_record(self):
        class Offline:
            def fetch(self,url):raise ValueError('offline')
        sets,payload=self.sample();catalog={'collections':[ygo_collections(sets,payload)[0][0]]};old=copy.deepcopy(catalog)
        checks,updates,state=refresh(Path('.'),catalog,Offline(),{}, {'tcg_catalogs':{'enabled':True}})
        self.assertFalse(updates);self.assertEqual(catalog,old);self.assertEqual(len(checks),2)
        self.assertNotIn('ygo_checked_epoch',state)

    def test_large_feed_is_not_requested_during_48_hour_cache(self):
        import time
        calls=[]
        class Offline:
            def fetch(self,url):calls.append(url);raise ValueError('offline')
        refresh(Path('.'),{'collections':[]},Offline(),{'tcg_state':{'ygo_checked_epoch':time.time()}},{'tcg_catalogs':{'enabled':True}})
        self.assertEqual(calls,['https://en.onepiece-cardgame.com/cardlist/'])

    def test_naruto_reviewed_guides_have_distinct_mission_ids(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'checklists-publicas.json').read_text())
        naruto=[c for c in data['collections'] if c['id'].startswith('cicaboom-naruto')]
        self.assertEqual(sorted(len(c['cards']) for c in naruto),[158,158,168])
        for c in naruto:
            self.assertEqual(len({x['source_key'] for x in c['cards']}),len(c['cards']))
            self.assertEqual(sum(x['section']=='Misiones' for x in c['cards']),10)
            self.assertFalse(any('Legendary' in x['tag'] or 'POP'==x['tag'] for x in c['cards']))
