"""Import the user's FIFA 365 2027 transcription, never certify it as official.

Input is a pdftotext -layout export. The PDF itself and its personal metadata
are never published. Append-only updates keep all previously assigned card IDs.
"""
import argparse
import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

COLLECTION_ID='panini-adrenalyn-xl-fifa365-2027'

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value)).split())

def key(value):
    return normalize(value).casefold()

def parse(text):
    start=text.find('Golden Baller')
    if start<0:
        raise ValueError('missing_first_section')
    section=None; cards=[]; seen=set()
    for raw in text[start:].replace('\f','\n').splitlines():
        line=normalize(raw)
        if not line:
            continue
        if not line.startswith('·'):
            section=line
            continue
        if not section:
            raise ValueError('missing_card_section')
        # Superscript counts in the supplied list are unrelated to card numbers.
        match=re.fullmatch(r'·\s*(.*?)\s+(\d+)',line)
        if not match:
            raise ValueError('unrecognized_row:'+line)
        label=match[1]
        numbered=re.fullmatch(r'((?:[A-Z]+\s+)?[A-Z]*-?\d+)\.\-\s*(.+)',label)
        if numbered:
            source_identifier,description=numbered.groups()
            source_identifier=normalize(source_identifier)
            identity='number:'+key(source_identifier)
            number=int(source_identifier) if source_identifier.isdigit() else source_identifier
            prefix=''
        else:
            unnumbered=re.fullmatch(r'([A-Z]+)\s+(.+)',label)
            if not unnumbered:
                raise ValueError('unrecognized_unnumbered_row:'+label)
            prefix,description=unnumbered.groups()
            source_identifier=None;number=prefix
            identity='unnumbered:'+key(section+'|'+label)
        if identity in seen:
            raise ValueError('duplicate_source_identifier:'+identity)
        seen.add(identity)
        # Preserve the supplied spelling. Team codes may precede or follow names.
        team=''
        team_first=re.fullmatch(r'([A-Z]{3})\s+(.+)',description)
        team_last=re.fullmatch(r'(.+)\s+([A-Z]{3})',description)
        if not numbered and team_first:
            team,player=team_first.groups()
        elif team_last:
            player,team=team_last.groups()
        else:
            player=description
        card={'id':COLLECTION_ID+'-'+hashlib.sha256(identity.encode()).hexdigest()[:20],
            'n':number,'player':player,'team':team,'section':section,
            'original_identifier':source_identifier,'source_identifier':source_identifier,
            'source_label':label,'identifier_basis':'user_provided_list',
            'source_key':identity,'parallels':[]}
        cards.append(card)
    if not cards:
        raise ValueError('empty_checklist')
    return cards

def merge_cards(old, incoming):
    """Retain older entries and IDs even if a later source omits them."""
    prior={c['source_key']:c for c in old}
    if len(prior)!=len(old):
        raise ValueError('ambiguous_previous_source_keys')
    merged=[];seen=set()
    for card in incoming:
        previous=prior.get(card['source_key'])
        merged.append({**copy.deepcopy(previous or {}),**card,
            'id':previous['id'] if previous else card['id']})
        seen.add(card['source_key'])
    merged.extend(copy.deepcopy(c) for c in old if c['source_key'] not in seen)
    return merged

def import_into(catalog, text):
    result=copy.deepcopy(catalog);incoming=parse(text)
    existing=next((c for c in result['collections'] if c['id']==COLLECTION_ID),None)
    previous=existing.get('cards',[]) if existing else []
    cards=merge_cards(previous,incoming)
    numbered={c['n'] for c in incoming if isinstance(c['n'],int)}
    missing=sorted(set(range(1,max(numbered,default=0)+1))-numbered)
    if missing:
        raise ValueError('numbered_range_has_gaps:'+str(missing))
    if existing and existing.get('cards')==cards:
        return result
    collection={**(existing or {}),'id':COLLECTION_ID,
        'name':'Panini Adrenalyn XL FIFA 365 2027','season':'2026/27','brand':'Panini',
        'category':'Fútbol','cards':cards,'card_count':len(cards),
        'checklistVersion':int((existing or {}).get('checklistVersion',0))+1,
        'checklist_status':'initial_user_provided','cover_status':'pending_official_cover',
        'source':'Listado inicial aportado por el usuario. Colección en actualización; no es un listado oficial certificado.',
        'expected_note':f'{len(cards)} entradas en {len(set(c["section"] for c in cards))} secciones. Listado inicial en actualización.',
        'source_url':'https://cromosrepes.com/coleccion/cromos/ADRENALYN-XL-FIFA-365-2027',
        'verification':{'complete':False,'input':'user_provided_pdf_transcription',
            'source_rows':len(incoming),'numbered_rows':len(numbered),
            'numbered_range':[min(numbered),max(numbered)],'numbered_missing':missing,
            'official_completeness_verified':False,
            'sections':dict(Counter(c['section'] for c in cards))}}
    # checklist_url is reserved for lazy Magic shards by the installed app.
    # Keep all FIFA cards inline so Android/PWA 1.8 can add this collection.
    collection.pop('checklist_url',None)
    if existing:
        result['collections'][result['collections'].index(existing)]=collection
    else:
        result['collections'].append(collection)
    result['version']=int(result.get('version',0))+1
    result['updated']=datetime.now(timezone.utc).date().isoformat()
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--text',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    catalog=import_into(json.loads(args.catalog.read_text()),args.text.read_text())
    args.output.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(catalog["collections"])} colecciones; FIFA 365 2027: '+
        str(len(next(c for c in catalog['collections'] if c['id']==COLLECTION_ID)['cards']))+' entradas')
