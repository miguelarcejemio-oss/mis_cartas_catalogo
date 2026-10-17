"""Refresh public checklist facts, retaining cached evidence and every stable card ID.

This path imports individually reviewed facts. Discovery metadata alone never
creates cards. Unreadable sources keep the last snapshot and report the failure.
"""
import copy
import hashlib
import json
from datetime import datetime, timezone
from scripts.public_checklists import PARSERS, validate

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def cards_with_ids(target, cards):
    validate(cards)
    result=copy.deepcopy(cards)
    for card in result:
        card['id']=target['id']+'-'+hashlib.sha256(card['source_key'].encode()).hexdigest()[:20]
    return result

def publish(catalog, target, cards, checked_at):
    cards=cards_with_ids(target,cards)
    existing=next((c for c in catalog['collections'] if c['id']==target['id']),None)
    previous={c['id']:c for c in existing['cards']} if existing else {}
    incoming={c['id']:c for c in cards}
    if previous.keys()-incoming.keys():raise ValueError('source_removed_existing_cards_review_required')
    for key,old in previous.items():
        # A changed title may be a source correction, but may also be a reused
        # printed number / wrong edition. Require review before moving a mark.
        if old['player']!=incoming[key]['player'] or old.get('section')!=incoming[key].get('section'):
            raise ValueError('existing_card_identity_changed_review_required:'+key)
        old_variants={v['id'] for v in old.get('parallels',[])}
        if old_variants-{v['id'] for v in incoming[key].get('parallels',[])}:
            raise ValueError('source_removed_existing_variants_review_required')
    if existing and existing.get('cards')==cards:return False
    record=copy.deepcopy(existing) if existing else {
        'id':target['id'],'name':target['name'],'season':target['season'],
        'brand':target['brand'],'country':target.get('country','España'),
        'category':target['category'],'source_url':target['source_url']}
    record.update(cards=cards,card_count=len(cards),source=target['note'],
        checklistVersion=int(record.get('checklistVersion',0))+1,
        checklistSourceUrl=target['source_url'],expected_note=target['note'],
        checklist_status='initial_verified_records',
        verification={'complete':False,'individual_records_verified':True,
            'scope':target['scope'],'required_card_count':None,'blockers':[],
            'source_evidence':target['evidence'],'checked_at':checked_at,
            'source_fingerprint':digest(cards)})
    if target.get('edition_verification'):
        record['verification']['edition_verification']=target['edition_verification']
    if existing:existing.clear();existing.update(record)
    else:catalog['collections'].append(record)
    return True

def refresh(root, catalog, client, live=True):
    path=root/'checklists-publicas.json'
    if not path.exists():return [],[]
    data=json.loads(path.read_text(encoding='utf-8'))
    stamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    checks=[];updates=[];changed=False
    for target in data['collections']:
        check={'id':target['id'],'source_url':target['source_url'],'blockers':[]}
        cards=target['cards'];fresh=False
        if live:
            try:
                if target.get('edition_verification')=='numbering_crosscheck_only':
                    raise ValueError('spanish_edition_images_and_titles_pending_review')
                _,_,raw=client.fetch(target['source_url'])
                if target['adapter']=='reviewed_pdf':
                    if hashlib.sha256(raw).hexdigest()!=target['document_sha256']:
                        raise ValueError('illustrated_pdf_changed_manual_review_required')
                else:
                    cards=PARSERS[target['adapter']](raw)
                    if len(cards)<target['minimum_records']:raise ValueError('checklist_truncated')
                    # Existing source snapshot also protects a first publication
                    # from a wrong edition / selector matching only part of a list.
                    old={c['source_key']:c for c in target['cards']}
                    new={c['source_key']:c for c in cards}
                    if old.keys()-new.keys():raise ValueError('source_removed_reviewed_records')
                    for key,c in old.items():
                        if (c['player'],c['section'])!=(new[key]['player'],new[key]['section']):
                            raise ValueError('source_changed_reviewed_identity:'+key)
                fresh=True
            except Exception as exc:
                check['blockers'].append({'code':getattr(exc,'code',type(exc).__name__),'detail':str(exc)})
                cards=target['cards']
        try:
            if publish(catalog,target,cards,stamp):updates.append(target['id'])
            if fresh:
                check['status']='checked_unchanged' if cards==target['cards'] else 'updated'
                if cards!=target['cards']:target['cards']=cards;changed=True
            else:check['status']='reviewed_snapshot_retained'
            check['verified_records']=len(cards)
        except Exception as exc:
            check['status']='blocked';check['blockers'].append({'code':type(exc).__name__,'detail':str(exc)})
        checks.append(check)
    if changed:
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return checks,updates
