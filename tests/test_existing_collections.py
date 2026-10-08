import copy
import unittest
from unittest.mock import patch
from scripts.existing_collections import match_existing,merge_verified,enrich_existing

class ExistingTests(unittest.TestCase):
    def candidate(self,brand='Editorial Desconocida'):
        return {'name':'Liga Prueba 2026','year':'2026','publisher':brand,'detail_url':'https://example.org/checklist'}
    def collection(self):
        return {'id':'keep','name':'Liga Prueba 2026','brand':'Editorial Desconocida','cards':[{'id':'personal','n':1,'have':True,'status':'Falta','future_state':{'x':1}}]}
    def record(self):
        return {'cards':[{'id':'foreign','n':'01','player':'Ana','team':'Club','section':'Base'}],
            'verification':{'complete':True},'checklist_url':'https://example.org/list','source_url':'https://example.org/checklist','cover_url':None}
    def test_unknown_manufacturer_matches_existing(self):
        candidate=self.candidate();self.assertEqual(match_existing(self.collection(),[candidate]),(candidate,None))
    def test_ambiguous_match_stays_pending(self):
        self.assertEqual(match_existing(self.collection(),[self.candidate(),self.candidate()])[1],'ambiguous_collection_identity')
    def test_distinct_season_does_not_match(self):
        candidate=self.candidate();candidate.update(name='Liga Prueba 2025',year='2025')
        self.assertIsNone(match_existing(self.collection(),[candidate])[0])
    def test_merge_preserves_every_personal_field_and_id(self):
        original=self.collection();before=copy.deepcopy(original);out=merge_verified(original,self.record())
        self.assertEqual(original,before)
        for key in ('id','n','have','status','future_state'):
            self.assertEqual(out['cards'][0][key],original['cards'][0][key])
        self.assertEqual(out['id'],'keep')
    def test_unmatched_existing_card_cannot_be_deleted(self):
        record=self.record();record['cards'][0]['n']='2'
        with self.assertRaisesRegex(ValueError,'migration'):
            merge_verified(self.collection(),record)
    def test_all_existing_records_included_even_when_limit_zero(self):
        catalog={'collections':[self.collection(),{'id':'other','name':'Otra 2026','brand':'Nueva','cards':[]}]}
        checks,published,attempts=enrich_existing(catalog,[self.candidate()],{},None,{},0)
        self.assertEqual({r['id'] for r in checks},{'keep','other'});self.assertEqual(published,[]);self.assertEqual(attempts,0)
    def test_existing_collection_is_updated_instead_of_skipped(self):
        catalog={'collections':[self.collection()]}
        with patch('scripts.enrich_collections.verify_collection',return_value=(self.record(),{})):
            checks,published,_=enrich_existing(catalog,[self.candidate()],{},None,{},1)
        self.assertEqual(published,['keep']);self.assertEqual(checks[0]['status'],'verified')
        self.assertEqual(catalog['collections'][0]['cards'][0]['id'],'personal')
    def test_existing_official_reference_used_without_index_match(self):
        collection=self.collection();collection['official_url']='https://publisher.example/2026/checklist'
        catalog={'collections':[collection]}
        with patch('scripts.enrich_collections.verify_collection',return_value=(self.record(),{})) as verify:
            checks,published,_=enrich_existing(catalog,[],{},None,{},1)
        self.assertEqual(verify.call_args.args[0]['detail_url'],collection['official_url'])
        self.assertEqual(checks[0]['source_kind'],'existing_public_reference')
        self.assertEqual(published,['keep'])
