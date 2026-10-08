import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from scripts import enrich_collections as e

PAGE = b'''<h1>Coleccion Prueba - 2026 - Nueva Marca</h1>
<table><tr><td>Descripcion</td></tr><tr><td>Total 2 cartas
<img src="/cover.png" alt="Portada album Coleccion Prueba"></td></tr></table>
<table><tr><th>Numero</th><th>Nombre</th><th>Serie</th></tr>
<tr><td>01</td><td>Ana</td><td>Base</td></tr><tr><td>EL-1</td><td>Firma impresa</td><td>Limitada</td></tr></table>
<table><tr><th>Usuario</th><th>Faltas</th><th>Repes</th></tr><tr><td>Privado</td><td>10</td><td>20</td></tr></table>'''
URL = 'https://cromosrepes.com/coleccion/cromos/PRUEBA'
ITEM = {'name': 'Coleccion Prueba', 'year': '2026', 'publisher': 'Nueva Marca', 'detail_url': URL}
CONFIG = {'reuse_permissions': [{'host': 'cromosrepes.com', 'publication_allowed': True, 'evidence_url': 'https://example.org/written-permission'}]}

class FakeClient:
    def fetch(self, url):
        if url.endswith('.png'):
            out=io.BytesIO();Image.new('RGB',(200,300)).save(out,format='PNG')
            return url, 'image/png', out.getvalue()
        return url, 'text/html', PAGE

class EnrichmentTests(unittest.TestCase):
    def test_social_table_excluded(self):
        detail=e.parse_detail(PAGE,URL)
        self.assertNotIn('Privado', str(detail))
        self.assertEqual([x['n'] for x in e.parse_cards(detail)], ['01','EL-1'])
    def test_unknown_publisher_verified_without_allowlist(self):
        record,_=e.verify_collection(ITEM,FakeClient(),CONFIG)
        self.assertEqual(record['brand'],'Nueva Marca')
        self.assertEqual(record['card_count'],2)
        self.assertEqual(record['cards'][1]['player'],'Firma impresa')
    def test_no_permission_no_publication(self):
        record,detail=e.verify_collection(ITEM,FakeClient(),{})
        self.assertIsNone(record)
        self.assertEqual(detail['blockers'][0]['code'],'reuse_not_authorized')
    def test_incomplete_count_rejected(self):
        class Partial(FakeClient):
            def fetch(self,url):
                final,ct,data=super().fetch(url)
                return final,ct,data.replace(b'Total 2 cartas',b'Total 3 cartas')
        record,detail=e.verify_collection(ITEM,Partial(),CONFIG)
        self.assertIsNone(record)
        self.assertIn('complete_count_not_verified',str(detail))
    def test_duplicate_ids_rejected(self):
        detail=e.parse_detail(PAGE.replace(b'EL-1',b'01'),URL)
        with self.assertRaisesRegex(ValueError,'duplicate'):e.parse_cards(detail)
    def test_empty_response_identified(self):
        with self.assertRaises(e.Blocked) as error:e.parse_detail(b'\n\n',URL)
        self.assertEqual(error.exception.code,'empty_or_unrecognized_detail')
    def test_http_block_does_not_stop_queue(self):
        class Fail(FakeClient):
            def fetch(self,url):
                if url.endswith('BLOCK'):raise e.Blocked('http_error',url,'HTTP 403 Forbidden')
                return super().fetch(url)
        with tempfile.TemporaryDirectory() as tmp:
            root=self.setup_root(tmp,CONFIG,[{**ITEM,'name':'Blocked','detail_url':URL+'BLOCK'},ITEM])
            report=e.run(root,client=Fail())
            self.assertEqual(len(report['published']),1)
            self.assertIn('HTTP 403',str(report['pending_review']))
    def setup_root(self,tmp,config,items):
        root=Path(tmp);(root/'portadas').mkdir()
        e.save(root/'fuentes.json',config)
        e.save(root/'catalogo.json',{'collections':[{'id':'existing','name':'Anterior','cards':[{'id':'keep','have':True}],'state':{'keep':True}}]})
        e.save(root/'portadas/descubrimiento.json',{'new_candidates':items})
        return root
    def test_catalog_byte_unchanged_when_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.setup_root(tmp,{},[ITEM]);before=(root/'catalogo.json').read_bytes()
            e.run(root,client=FakeClient())
            self.assertEqual(before,(root/'catalogo.json').read_bytes())
    def test_append_preserves_state_and_second_run_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.setup_root(tmp,CONFIG,[ITEM]);before=e.load(root/'catalogo.json',{})['collections'][0]
            e.run(root,client=FakeClient());after=e.load(root/'catalogo.json',{})
            self.assertEqual(before,after['collections'][0]);self.assertEqual(len(after['collections']),2)
            second=e.run(root,client=FakeClient());self.assertEqual(second['published'],[])
    def test_pdf_extracts_only_when_complete(self):
        from unittest.mock import patch, Mock
        page=Mock();page.extract_text.return_value='Coleccion Prueba 2026\nTotal 2 cartas\n01 Ana\nEL-1 Firma impresa'
        reader=Mock();reader.is_encrypted=False;reader.pages=[page]
        with patch('pypdf.PdfReader',return_value=reader):
            detail=e.parse_pdf(b'%PDF-',ITEM)
            self.assertEqual(len(e.parse_cards(detail)),2)
            page.extract_text.return_value='Coleccion Prueba 2026\nTotal 3 cartas\n01 Ana\nEL-1 Firma impresa'
            with self.assertRaisesRegex(ValueError,'incomplete'):e.parse_pdf(b'%PDF-',ITEM)
    def test_original_autographs_excluded_printed_kept(self):
        class Original(FakeClient):
            def fetch(self,url):
                final,ct,data=super().fetch(url)
                return final,ct,data.replace(b'<td>Ana</td><td>Base',b'<td>Ana</td><td>Autografo original')
        record,_=e.verify_collection(ITEM,Original(),CONFIG)
        self.assertEqual(record['card_count'],1)
        self.assertEqual(record['cards'][0]['n'],'EL-1')
    def test_reports_separate(self):
        from scripts import collection_discovery as d
        from scripts import detect_updates as u
        self.assertNotEqual(d.REPORT,u.REPORT)
        self.assertEqual(e.DISCOVERY,d.REPORT)

if __name__=='__main__':unittest.main()
