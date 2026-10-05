#!/usr/bin/env python3
import json,sys
p=sys.argv[1] if len(sys.argv)>1 else 'catalogo.json'
d=json.load(open(p,encoding='utf-8'))
cols=d.get('collections',[])
assert isinstance(cols,list) and cols, 'collections vacío'
ids=[c.get('id') for c in cols]
assert all(ids) and len(ids)==len(set(ids)), 'IDs de colección duplicados o vacíos'
total=0
warnings=[]
for c in cols:
    cards=c.get('cards',[])
    assert isinstance(cards,list), f'cards inválido: {c.get("id")}'
    cids=[x.get('id') for x in cards]
    assert all(cids) and len(cids)==len(set(cids)), f'IDs de carta duplicados/vacíos: {c.get("id")}'
    total += len(cards)
    declared=c.get('card_count')
    if isinstance(declared,int) and declared != len(cards):
        warnings.append(f'{c.get("id")}: declaradas {declared}, cargadas {len(cards)} (se permite checklist parcial/catalog-only)')
print(f'OK: {len(cols)} colecciones, {total} cartas')
for w in warnings[:20]: print('AVISO:',w)
if len(warnings)>20: print(f'AVISO: {len(warnings)-20} avisos adicionales')
