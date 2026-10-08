"""Publication invariants independent of HTTP availability and personal state."""
import copy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts import official_checklists as o

TEXT = '''2ª edición 3ª edición
ELITE
1 Ana (Club)
DEPORTIVO ALAVÉS
19 ESCUDO
21 BIS Bea
FLASHBACK ANTHOLOGY
433 Ana / Bea,
Celia.
NUEVOS FICHAJES
442 Celia
ELITE POWER
P1 Ana (Club)
INSERTS
SPECIAL ONE BLACK (11. Inserts)
Ana
SPECIAL ONE GOLD (3. Inserts)
Bea
AUTÓGRAFOS
200 autógrafos
Firma real
CARDS ÍNDICE
IN21 2ª Edición - 1
'''

class OfficialTests(unittest.TestCase):
    def parse(self, text=TEXT):
        with patch.object(o, 'PdfReader', return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:text)])):
            return o.pdf_rows(b'fixture')
    def test_original_bis_and_power_identifiers(self):
        cards,_=self.parse()
        self.assertIn('21 BIS', [c['original_identifier'] for c in cards])
        self.assertIn('P1', [c['original_identifier'] for c in cards])
    def test_unnumbered_inserts_not_assigned_invented_numbers(self):
        cards,_=self.parse()
        self.assertTrue(all(c['original_identifier'] is None and c['n'] is None for c in cards if c['section'].startswith('SPECIAL')))
    def test_autographs_excluded(self):
        cards,excluded=self.parse()
        self.assertEqual(excluded,1)
        self.assertNotIn('Firma real',str(cards))
    def test_multiline_description_preserved(self):
        cards,_=self.parse()
        self.assertEqual(next(c['player'] for c in cards if c['n']=='433'),'Ana / Bea, Celia.')
    def test_duplicate_printed_id_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_pdf_identifier'):
            self.parse(TEXT+'\nIN21 Otra\n')
    def test_unknown_text_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'unrecognised'):
            self.parse(TEXT+'\nFormato desconocido\n')
    def test_shop_includes_unavailable_cards(self):
        rows=[{'identifier':'001','isAvailable':False}]
        data={'*':{'Magento_Ui/js/core/app':{'components':{'missing_stickers':{'missingStickers':rows}}}}}
        html='<script type="text/x-magento-init">'+json.dumps(data)+'</script>'
        self.assertIn('1',o.shop_rows(html))
    def test_shop_challenge_never_treated_as_empty_collection(self):
        with self.assertRaisesRegex(ValueError,'challenge'):
            o.shop_rows('<noscript>Activa JavaScript</noscript>')
    def test_incomplete_collection_cannot_replace_existing(self):
        catalog={'collections':[{'id':'test','cards':[{'id':'old','n':1,'have':True}]}]}
        before=copy.deepcopy(catalog)
        self.assertFalse(o.publish_existing(catalog,{'collection_id':'test'},[],{'complete':False,'blockers':['incomplete']}))
        self.assertEqual(catalog,before)
    def test_complete_merge_preserves_ids_numbers_states_and_other_collections(self):
        catalog={'collections':[{'id':'test','cards':[{'id':'old','n':1,'have':True,'status':'Falta'}]}, {'id':'other','cards':[]}]}
        cards=[{'key':'1','n':'1','player':'Ana','team':'Club','section':'ELITE','original_identifier':'1'}]
        self.assertTrue(o.publish_existing(catalog,{'collection_id':'test'},cards,{'complete':True,'blockers':[]}))
        self.assertEqual(catalog['collections'][0]['cards'][0]['id'],'old')
        self.assertEqual(catalog['collections'][0]['cards'][0]['n'],1)
        self.assertTrue(catalog['collections'][0]['cards'][0]['have'])
        self.assertEqual(catalog['collections'][0]['cards'][0]['status'],'Falta')
        self.assertEqual(catalog['collections'][1],{'id':'other','cards':[]})
    def test_invalid_legacy_identifiers_not_reassigned(self):
        catalog={'collections':[{'id':'test','cards':[{'id':'personal','n':'SOB7','have':True}]}]}
        with self.assertRaisesRegex(ValueError,'require_migration'):
            o.publish_existing(catalog,{'collection_id':'test'},[],{'complete':True,'blockers':[]})
    def test_identifier_normalization_keeps_original_separate(self):
        self.assertEqual(o.identifier('021 Bis'),'21 BIS')
        self.assertEqual(o.identifier('P005'),'P5')
        self.assertEqual(o.identifier('IN21'),'IN21')

    def test_official_677_cannot_publish_as_complete_692(self):
        cards=[{'key':str(i),'n':str(i),'player':'Ana','team':'Club','section':'Base','original_identifier':str(i)} for i in range(1,678)]
        target={'collection_id':'test','checklist_url':'https://example.org/list.pdf','shop_url':'https://example.org/shop','required_card_count':692}
        client=SimpleNamespace(fetch=lambda url:(url,'text/html',b'<html></html>'))
        config={'reuse_permissions':[{'host':'example.org','publication_allowed':True,'evidence_url':'https://example.org/permission'}]}
        with patch.object(o,'pdf_rows',return_value=(cards,26)),patch.object(o,'shop_rows',return_value={'1':{'identifier':'001','description':'Ana'}}):
            result,_=o.verify_official(target,client,config)
        self.assertFalse(result['complete'])
        self.assertIn({'code':'incomplete_collection','verified':677,'required':692,'missing':15,'detail':'Faltan promocionales: no publicar una edición como colección completa'},result['blockers'])

    def test_explicit_unnumbered_supplement_keeps_null_original_id(self):
        detail={'tables':[['Numero','Nombre','Serie'],['S/N','Ana','Top Fichaje'],['24 BIS','Bea','Last Moment']]}
        # Each table is a list of rows.
        detail={'tables':[detail['tables']]}
        cards=o.parse_supplement(detail)
        self.assertIsNone(cards[0]['original_identifier'])
        self.assertEqual(cards[0]['key'],'TOP FICHAJE:Ana')
        self.assertEqual(cards[1]['original_identifier'],'24 BIS')
    def test_empty_number_is_not_assumed_unnumbered(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):
            o.parse_supplement({'tables':[[['Numero','Nombre','Serie'],['','Ana','Top Fichaje']]]})
    def test_legacy_unnumbered_match_keeps_personal_state_and_archives_mistake(self):
        valid={'id':'my-gavi','n':'SOB3','player':'Gavi','section':'Special One Black','have':True}
        invalid={'id':'my-courtois','n':'SOB7','player':'Courtois','section':'Special One Black','status':'Falta'}
        catalog={'collections':[{'id':'test','cards':[valid,invalid]}]}
        cards=[{'key':'SPECIAL ONE BLACK:Gavi','n':None,'player':'Gavi','team':'','section':'SPECIAL ONE BLACK','original_identifier':None}]
        o.publish_existing(catalog,{'collection_id':'test'},cards,{'complete':True,'blockers':[]})
        result=catalog['collections'][0]
        self.assertEqual(result['cards'][0]['id'],'my-gavi')
        self.assertTrue(result['cards'][0]['have'])
        self.assertEqual(result['legacy_unverified_cards'],[invalid])
        o.publish_existing(catalog,{'collection_id':'test'},cards,{'complete':True,'blockers':[]})
        self.assertEqual(result['legacy_unverified_cards'],[invalid])
