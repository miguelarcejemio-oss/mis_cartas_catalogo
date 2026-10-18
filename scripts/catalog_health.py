"""Public aggregate health: fetching a source does not mean publishing updates."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]

def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}

def health(root=ROOT):
    discovery=read(root/'portadas/descubrimiento.json')
    enrichment=read(root/'portadas/enriquecimiento.json')
    catalog=read(root/'catalogo.json')
    candidates={}
    for item in discovery.get('pending_review',[])+enrichment.get('pending_review',[]):
        key=unquote(str(item.get('detail_url') or '')).replace('/coleccion/ficha/','/coleccion/cromos/').rstrip('/') or item.get('identity_key') or item.get('name')
        if key:candidates[key]={**candidates.get(key,{}),**item}
    pending=list(candidates.values())
    reasons={}
    failed_checks=[item for item in enrichment.get('existing_checks',[])+enrichment.get('official_checks',[])+enrichment.get('public_checklist_checks',[])
        if item.get('blockers')]
    for item in pending+failed_checks:
        for blocker in item.get('blockers',[]):
            code=blocker.get('code','unknown')
            reasons[code]=reasons.get(code,0)+1
    sources=discovery.get('checked_sources',[])
    live=[s for s in sources if s.get('type') in ('catalog_index','recent_collections','public_catalog_api')]
    errors=len(discovery.get('errors',[]))+len(enrichment.get('errors',[]))
    if not live or not any(s.get('status')=='ok' for s in live):
        status='source_error'
    elif errors or reasons or pending:
        status='pending_verification'
    else:
        status='checked'
    return {'schema_version':1,'checked_at':datetime.now(timezone.utc).isoformat(),
        'discovery_checked_at':discovery.get('checked_at'),
        'enrichment_checked_at':enrichment.get('checked_at'),
        'status':status,'catalog_updated_at':catalog.get('updated_at',catalog.get('updated')),
        'catalog_version':catalog.get('version'),'collections':len(catalog.get('collections',[])),
        'published_this_run':len(enrichment.get('published',[])),
        'pending_verification':len(pending),'blocking_reasons':reasons,'errors':errors,
        'existing_checks_blocked':len(failed_checks),
        'tcg_source_pending':sum(len(x.get('pending',[])) for x in enrichment.get('tcg_checks',[])),
        'tcg_source_errors':sum(bool(x.get('error')) for x in enrichment.get('tcg_checks',[])),
        'metadata_details_pending':sum(s.get('details_pending',0) for s in live),
        'discovery_coverage':'partial',
        'sources':[{'type':s.get('type'),'status':s.get('status'),
            'coverage':s.get('coverage','partial'),'collections_found':s.get('collections_found',0)} for s in live]}

def run(root=ROOT):
    result=health(root)
    (root/'catalog-health.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    message=(f"Catálogo: {result['collections']} colecciones; "
        f"{result['published_this_run']} publicadas en esta ejecución; "
        f"{result['pending_verification']} pendientes; cobertura parcial.")
    print(message)
    if result['status']!='checked':
        print('::warning title=Actualización de catálogo incompleta::'+message)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as stream:
            stream.write('### Estado del catálogo\n\n'+message+'\n\nEstado: '+result['status']+'\n')
    return result

if __name__=='__main__':
    run()
