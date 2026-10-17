import copy
import unittest
from scripts.import_fifa365_pdf import parse, import_into, COLLECTION_ID

SAMPLE='''Golden Baller
·1.- GB Marquinhos BRA 450
·2.- Invincible 441
Fan Favourite
·FFNXI 352.- Josep Martínez INT 1600
Rising Star
·RS01.- Rio Ngumoha LIV 550
Edición Limitada
·LE FCB Lamine Yamal 1780
'''

class FifaImportTests(unittest.TestCase):
    def test_numbers_and_unnumbered_identity(self):
        rows=parse(SAMPLE)
        self.assertEqual([r['n'] for r in rows],[1,2,'FFNXI 352','RS01','LE'])
        self.assertEqual(rows[0]['player'],'GB Marquinhos')
        self.assertEqual(rows[-1]['player'],'Lamine Yamal')
        self.assertEqual(rows[-1]['team'],'FCB')
        self.assertIsNone(rows[-1]['original_identifier'])
        self.assertNotIn('1780',str(rows))
        self.assertEqual(len(set(c['id'] for c in rows)),5)

    def test_existing_catalog_is_preserved_and_import_is_idempotent(self):
        original={'version':18,'collections':[{'id':'old','name':'Anterior',
            'cards':[{'id':'stable','have':True,'status':'La tengo'}]}]}
        before=copy.deepcopy(original)
        result=import_into(original,SAMPLE)
        self.assertEqual(original,before)
        self.assertEqual(result['collections'][0],before['collections'][0])
        self.assertEqual(import_into(result,SAMPLE),result)
        self.assertFalse(result['collections'][1]['verification']['complete'])
        self.assertNotIn('checklist_url',result['collections'][1])

    def test_extension_keeps_ids_and_omitted_cards(self):
        old=import_into({'version':1,'collections':[]},SAMPLE)
        before={c['source_key']:c['id'] for c in old['collections'][0]['cards']}
        extended=import_into(old,SAMPLE+'·LE NOR Erling Haaland 168\n')
        after=extended['collections'][0]['cards']
        self.assertEqual(len(after),6)
        self.assertTrue(all(next(c for c in after if c['source_key']==k)['id']==v for k,v in before.items()))
        reduced=import_into(extended,SAMPLE)
        self.assertEqual(len(reduced['collections'][0]['cards']),6)

    def test_duplicate_or_missing_number_fails(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            parse(SAMPLE+'Golden Baller\n·1.- Duplicate BRA 2\n')
        with self.assertRaisesRegex(ValueError,'range_has_gaps'):
            import_into({'version':1,'collections':[]},SAMPLE.replace('·2.- Invincible 441','·3.- Invincible 441'))

if __name__=='__main__':
    unittest.main()
