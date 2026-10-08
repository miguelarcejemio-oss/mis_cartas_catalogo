"""Match existing collections to public discovery metadata, without a brand allowlist."""
import copy
import re
import unicodedata
from urllib.parse import urlsplit


def words(value):
    value=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().casefold()
    return set(re.findall(r'[a-z]+|\d+',value))


def match_existing(collection, candidates):
    if collection.get('source_url'):
        exact=[item for item in candidates if item.get('detail_url')==collection['source_url']]
        if len(exact)==1:
            return exact[0], None
    brand=words(collection.get('brand',''))
    ignored={'la','liga','laliga','panini','coleccion','collection','cards','cartas','stickers','cromos'} | brand
    title=words(collection['name'])-ignored
    ranked=[]
    for candidate in candidates:
        if brand and words(candidate.get('publisher','')) != brand:
            continue
        incoming=words(candidate['name'])-ignored
        years={x for x in title if x.isdigit() and len(x)==4}
        source_years={x for x in incoming|words(candidate.get('year','')) if x.isdigit() and len(x)==4}
        if years and not years.intersection(source_years):
            continue
        if not title or not incoming:
            continue
        score=len(title&incoming)/len(title|incoming)
        if score>=0.8:
            ranked.append((score,candidate))
    ranked.sort(key=lambda row:row[0],reverse=True)
    if not ranked:
        return None, 'source_not_located'
    if len(ranked)>1 and ranked[0][0]-ranked[1][0]<0.1:
        return None, 'ambiguous_collection_identity'
    return ranked[0][1], None


def merge_verified(collection, record):
    """Build first, mutate only after proving every existing identifier is retained."""
    from scripts.official_checklists import identifier
    if not record.get('verification',{}).get('complete'):
        raise ValueError('incomplete_collection')
    old={identifier(card.get('original_identifier',card.get('n'))):card for card in collection['cards']}
    if len(old)!=len(collection['cards']):
        raise ValueError('ambiguous_existing_identifiers')
    incoming={identifier(card['n']):card for card in record['cards']}
    if len(incoming)!=len(record['cards']):
        raise ValueError('duplicate_source_identifiers')
    absent=set(old)-set(incoming)
    if absent:
        raise ValueError('existing_identifiers_require_migration:'+','.join(sorted(absent)))
    merged=[]
    for key,card in incoming.items():
        item=copy.deepcopy(old.get(key,card))
        # Preserve existing id/n and every personal field, even future unknown fields.
        item.update({k:card.get(k,'') for k in ('player','team','section')})
        item['original_identifier']=card['n']
        if key not in old:
            import hashlib
            item['id']=collection['id']+'-'+hashlib.sha256(key.encode()).hexdigest()[:16]
        merged.append(item)
    update=copy.deepcopy(collection)
    update.update(cards=merged,card_count=len(merged),verification=record['verification'],
                  checklist_url=record['checklist_url'],source_url=record['source_url'])
    if record.get('cover_url'):
        update.update(cover=record['cover_url'],cover_url=record['cover_url'])
    return update


def enrich_existing(catalog, candidates, config, client, previous, limit):
    from scripts.enrich_collections import verify_collection
    official={target['collection_id'] for target in config.get('official_checklists',[])}
    checks=[];published=[]
    last={item['id']:item.get('last_checked','') for item in previous.get('existing_checks',[])}
    ordered=sorted(catalog['collections'],key=lambda c:(last.get(c['id'],''),c['id']))
    attempts=0
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc).isoformat()
    for collection in ordered:
        report={'id':collection['id'],'card_count_before':len(collection['cards']),'status':'pending'}
        checks.append(report)
        if collection['id'] in official:
            report['status']='official_adapter';continue
        candidate,reason=match_existing(collection,candidates)
        if not candidate:
            public_url = collection.get('checklist_url') or collection.get('official_url')
            if public_url:
                season = str(collection.get('season', ''))
                year = re.search(r'20\d{2}', season + ' ' + collection['name'])
                candidate = {'name': collection['name'], 'publisher': collection.get('brand', ''),
                    'year': year.group() if year else season, 'detail_url': public_url}
                report['source_kind'] = 'existing_public_reference'
            else:
                report['blockers']=[{'code':reason}];continue
        report['source_url']=candidate['detail_url']
        if attempts>=limit:
            report['last_checked']=last.get(collection['id'],'');continue
        attempts+=1;report['last_checked']=now
        try:
            record,evidence=verify_collection(candidate,client,config)
            if record is None:
                report.update(status='blocked',blockers=evidence.get('blockers',[]));continue
            updated=merge_verified(collection,record)
            if updated != collection:
                collection.clear();collection.update(updated)
                published.append(collection['id'])
            report.update(status='verified',card_count_after=len(collection['cards']))
        except Exception as exc:
            report.update(status='blocked',blockers=[{'code':getattr(exc,'code',type(exc).__name__),
                'url':getattr(exc,'url',candidate['detail_url']),'detail':str(exc)}])
    return checks,published,attempts
