"""Factual public TCG checklists. No artwork, prices, effects or user data.

Passcodes identify Yu-Gi-Oh! cards; observed printed codes identify One Piece
cards. A missing, truncated or changed identity never deletes a saved card.
"""
import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from bs4 import BeautifulSoup

YGO_SETS='https://db.ygoprodeck.com/api/v7/cardsets.php'
YGO_CARDS='https://db.ygoprodeck.com/api/v7/cardinfo.php'
OP_LIST='https://en.onepiece-cardgame.com/cardlist/'

def key(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]

def ygo_id(item):
    return 'konami-yugioh-'+item['set_code'].lower()+'-'+key(item['set_name'])

def ygo_collections(sets, payload, today=None):
    today=today or date.today().isoformat()
    grouped=defaultdict(dict)
    for card in payload['data']:
        for printing in card.get('card_sets',[]):
            grouped[printing['set_name']].setdefault(str(card['id']), {'card':card,'prints':[]})['prints'].append(printing)
    result=[];pending=[]
    for item in sets:
        rows=grouped[item['set_name']]
        if item.get('tcg_date','')>today or not rows or len(rows)!=item['num_of_cards']:
            pending.append({'name':item['set_name'],'expected':item['num_of_cards'],'observed':len(rows),'reason':'future_or_incomplete_source'});continue
        cid=ygo_id(item);cards=[]
        for passcode,row in sorted(rows.items(),key=lambda x:int(x[0])):
            prints=sorted(row['prints'],key=lambda p:(0 if '-EN' in p['set_code'] else 1 if re.search(r'-\d',p['set_code']) else 2,p['set_code'],p['set_rarity']))
            variants=sorted({p['set_rarity'] for p in prints if not re.search(r'seriali[sz]ed|individually numbered|hand.?signed|original autograph',p['set_rarity'],re.I)})
            if not variants:continue
            cards.append({'id':cid+'-'+passcode,'n':prints[0]['set_code'],'player':row['card']['name'],
                'section':row['card'].get('type','Cartas'),'tag':variants[0],
                **({'parallels':[{'id':key(v),'name':v,'type':'Rareza opcional'} for v in variants]} if len(variants)>1 else {})})
        if len(cards)!=item['num_of_cards']:continue
        result.append({'id':cid,'name':'Yu-Gi-Oh! — '+item['set_name'],'season':item.get('tcg_date','')[:4] or 'Sin fecha',
            'brand':'Konami','country':'Internacional','category':'TCG','cards':cards,
            'source_url':'https://ygoprodeck.com/api-guide/','source':'YGOPRODeck, API pública. Nombres en inglés; una ficha por passcode en la expansión. Reimpresiones regionales agrupadas; código observado en la fuente.',
            'expected_note':'Checklist por carta única de la edición según la API; rarezas opcionales, sin precios ni textos de reglas.','checklist_status':'source_count_matched'})
    return result,pending

def one_piece_registry(raw):
    soup=BeautifulSoup(raw,'html.parser');rows=[]
    for o in soup.select('select[name="series"] option'):
        title=o.get_text(' ',strip=True);m=re.search(r'\[([A-Z0-9-]+)\]',title)
        if m and re.fullmatch(r'\d+',o.get('value','')) and re.fullmatch(r'(?:OP-\d+|OP\d+-EB\d+|EB-\d+|PRB-\d+)',m[1]):
            rows.append({'id':m[1],'series':o['value'],'name':title})
    if not rows:raise ValueError('one_piece_registry_empty')
    return rows

def one_piece_collection(item,raw):
    soup=BeautifulSoup(raw,'html.parser');grouped=defaultdict(list)
    for dl in soup.select('dl.modalCol'):
        info=dl.select('.infoCol span');name=dl.select_one('.cardName')
        if len(info)<3 or not name:raise ValueError('one_piece_row_changed')
        code=info[0].get_text(strip=True)
        if not re.fullmatch(r'[A-Z]+\d*-\d+',code):raise ValueError('one_piece_printed_code_changed:'+code)
        grouped[code].append((dl.get('id',''),name.get_text(' ',strip=True),info[1].get_text(strip=True),info[2].get_text(strip=True)))
    if len(grouped)<20:raise ValueError('one_piece_list_truncated')
    cid='bandai-one-piece-'+item['id'].lower().replace('-','')
    cards=[]
    for code,rows in sorted(grouped.items()):
        # Only numbered logical cards here. Alternate artwork cannot be inferred
        # from an image suffix; serial/signature finishes need separate review.
        chosen=next((r for r in rows if r[0]==code),sorted(rows)[0])
        cards.append({'id':cid+'-'+code.lower(),'n':code,'player':chosen[1],'section':chosen[3],'tag':chosen[2]})
    return {'id':cid,'name':'One Piece Card Game — '+BeautifulSoup(item['name'],'html.parser').get_text(' ',strip=True),'season':'Sin fecha',
        'brand':'Bandai','country':'Internacional','category':'TCG','cards':cards,
        'source_url':OP_LIST+'?series='+item['series'],
        'source':'Checklist oficial Bandai en inglés. Una ficha por número impreso, incluidas reimpresiones del producto. No incluye acabados ni ilustraciones alternativas como cartas obligatorias.',
        'expected_note':'Lista de números publicados por Bandai; no implica disponibilidad comercial local. Variantes pendientes de revisión.',
        'checklist_status':'official_numbered_records'}

def publish(catalog,incoming,stamp):
    record=copy.deepcopy(incoming);old=next((c for c in catalog['collections'] if c['id']==record['id']),None)
    oldcards={c['id']:c for c in old.get('cards',[])} if old else {}
    newcards={c['id']:c for c in record['cards']}
    if oldcards.keys()-newcards.keys():raise ValueError('source_removed_existing_cards')
    for cid,c in oldcards.items():
        if (c['player'],c.get('section'))!=(newcards[cid]['player'],newcards[cid].get('section')):raise ValueError('source_changed_existing_identity')
        if {p['id'] for p in c.get('parallels',[])}-{p['id'] for p in newcards[cid].get('parallels',[])}:raise ValueError('source_removed_variants')
    if old and old.get('cards')==record['cards']:return False
    record['card_count']=len(record['cards']);record['checklistVersion']=(old or {}).get('checklistVersion',0)+1
    record['checklistSourceUrl']=record['source_url']
    record['verification']={'complete':False,'individual_records_verified':True,'scope':record['expected_note'],'checked_at':stamp,
        'source_fingerprint':key(json.dumps(record['cards'],sort_keys=True,ensure_ascii=False))}
    if old:
        merged={**old,**record}
        if old.get('season') and record['season']=='Sin fecha':merged['season']=old['season']
        old.clear();old.update(merged)
    else:catalog['collections'].append(record)
    return True

def refresh(root,catalog,client,previous,config):
    checks=[];updates=[];state=copy.deepcopy(previous.get('tcg_state',{}))
    if not config.get('tcg_catalogs',{}).get('enabled'):return checks,updates,state
    now=datetime.now(timezone.utc);stamp=now.isoformat()
    def apply(records):
        for c in records:
            try:
                if publish(catalog,c,stamp):updates.append(c['id'])
            except Exception as e:checks.append({'id':c['id'],'status':'retained','error':str(e)})
    # Bulk feed is cached for at least 48 h as requested by its publisher.
    if (now.timestamp()-state.get('ygo_checked_epoch',0))>=48*3600:
        try:
            sets=json.loads(client.fetch(YGO_SETS)[2]);payload=json.loads(client.fetch(YGO_CARDS)[2])
            records,pending=ygo_collections(sets,payload);apply(records)
            checks.append({'family':'Yu-Gi-Oh!','accepted':len(records),'pending':pending})
            state['ygo_checked_epoch']=now.timestamp()
        except Exception as e:checks.append({'family':'Yu-Gi-Oh!','status':'retained','error':str(e)})
    # Rotate a bounded number of official lists; discover new products each run.
    try:
        registry=one_piece_registry(client.fetch(OP_LIST)[2]);cursor=state.get('op_cursor',0)%len(registry)
        budget=min(config['tcg_catalogs'].get('one_piece_budget',4),len(registry))
        for i in range(budget):
            item=registry[(cursor+i)%len(registry)]
            try:apply([one_piece_collection(item,client.fetch(OP_LIST+'?series='+item['series'])[2])])
            except Exception as e:checks.append({'id':item['id'],'status':'retained','error':str(e)})
        state['op_cursor']=(cursor+budget)%len(registry)
    except Exception as e:checks.append({'family':'One Piece','status':'retained','error':str(e)})
    return checks,updates,state
