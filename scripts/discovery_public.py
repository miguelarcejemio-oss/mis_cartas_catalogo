"""Broader public discovery. Metadata only: no users, inventories or artwork.

The endpoints below are those used by the site's public collection search.
Requests respect robots.txt and the server's five-second crawl delay.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit

PUBLIC='https://cromosrepes.com/api/public/'
DETAIL='https://cromosrepes.com/coleccion/cromos/'

def canonical(url):
    return unquote(str(url or '')).replace('/coleccion/ficha/','/coleccion/cromos/').rstrip('/')

def sitemap_urls(text):
    urls=[]
    for line in text.splitlines():
        url=line.strip();parts=urlsplit(url)
        if parts.scheme!='https' or parts.hostname!='cromosrepes.com':
            continue
        if not re.fullmatch(r'/coleccion/(?:cromos|ficha)/[^/]+',parts.path):
            continue
        if re.search(r'QUEDADA|EVENTO-DE-INTERCAMBIO|ENCUENTRO-DE-COLECCIONISTAS',unquote(parts.path),re.I):
            continue
        urls.append(canonical(url))
    return sorted(set(urls))

def norm(value):
    return re.sub(r'\s+',' ',str(value or '')).strip()

def metadata(row, publishers, source):
    name=norm(row.get('nombre'));slug=norm(row.get('escNombre'))
    if not name or not slug or '/' in slug or '?' in slug or '#' in slug:
        raise ValueError('invalid_public_collection_metadata')
    year=str(row.get('anoPublica',''))
    # Some genuine older collections have no year. Retain the public name and
    # maker rather than aborting the remaining 500 rows or guessing a year.
    if not re.fullmatch(r'\d{4}',year) or year=='9999':year=''
    publisher=publishers.get(row.get('editorialId'),'Desconocida')
    identity=re.sub(r'[^\w]+',' ',f'{name}|{year}|{publisher}'.lower()).strip()
    return {'stable_id':hashlib.sha256(identity.encode()).hexdigest()[:24],
        'identity_key':identity,'name':name,'year':year,'publisher':publisher,
        'publisher_source_id':row.get('editorialId'),'source_name':source['name'],
        'source_url':source['url'],'detail_url':DETAIL+slug,
        'status':'discovered','metadata_status':'verified_public_metadata' if year else 'publication_year_pending',
        'checklist_status':'not_verified','cover_status':'not_verified',
        'collection_type_source_id':row.get('tipoId')}

def run(source, previous, known_urls, client):
    base=source['url'].rstrip('/')
    publishers_url=source['publishers_url']
    if not base.startswith(PUBLIC) or not publishers_url.startswith(PUBLIC):
        raise ValueError('public_collection_endpoints_required')
    def get(url):
        # Quote non-ASCII slugs; never attach session cookies or credentials.
        _,_,data=client.fetch(quote(url,safe=':/?=&%'))
        return json.loads(data.decode('utf-8'))
    registry=get(publishers_url)
    if not isinstance(registry,list) or not registry:
        raise ValueError('empty_manufacturer_registry')
    publishers={int(p['id']):norm(p['nombre']) for p in registry
        if isinstance(p,dict) and isinstance(p.get('id'),int) and norm(p.get('nombre'))}
    if not publishers:raise ValueError('empty_valid_manufacturer_registry')
    found={};failures=[];capped=[];successful=0
    limit=int(source.get('result_limit',500))
    year=datetime.now(timezone.utc).year
    # The public HTML recent-collections feed is handled by the main discoverer.
    # Its separate API route returns 403; do not repeatedly request that route.
    queries=[('todas',0)]+[(str(y),0) for y in range(year-1,year+2)]
    # Manufacturers come from the live registry, never an allow-list in code.
    ordered=sorted(publishers)
    cursor=int(previous.get('publisher_cursor',0))%len(ordered)
    budget=min(max(int(source.get('publisher_budget',4)),0),len(ordered))
    chosen=[ordered[(cursor+i)%len(ordered)] for i in range(budget)]
    queries += [('todas',publisher) for publisher in chosen]
    for query,publisher in queries:
        url=base+'/'+quote(query) +'/'+str(publisher)+'/0'
        try:
            rows=get(url)
            if not isinstance(rows,list):raise ValueError('collection_array_required')
            if not rows and query=='todas':raise ValueError('empty_public_collection_index')
            successful+=1
            if len(rows)>=limit:capped.append({'query':query,'publisher_id':publisher})
            for row in rows:
                item=metadata(row,publishers,source)
                found[canonical(item['detail_url'])]=item
        except Exception as exc:
            failures.append({'url':url,'error':str(exc)})
    if not successful:raise ValueError('all_public_catalog_queries_failed')
    backlog=list(previous.get('url_backlog',[]));sitemap_count=0
    try:
        _,_,data=client.fetch(source['sitemap_url'])
        listed=sitemap_urls(data.decode('utf-8'))
        if not listed:raise ValueError('empty_collection_sitemap')
        sitemap_count=len(listed)
        # New URLs first; do not reset the old queue every time a request fails.
        old=set(previous.get('sitemap_urls',[]))
        backlog=[u for u in listed if u not in old]+backlog+[u for u in listed if u in old]
    except Exception as exc:
        failures.append({'url':source['sitemap_url'],'error':str(exc)})
        listed=previous.get('sitemap_urls',[])
    known={canonical(u) for u in known_urls}|set(found)
    backlog=list(dict.fromkeys(canonical(u) for u in backlog if canonical(u) not in known))
    # Recent editions before the historical backlog; preserve order within each
    # group so older URLs still progress rather than resetting their queue.
    recent=re.compile('|'.join(str(y) for y in range(year-1,year+2)))
    backlog.sort(key=lambda u:0 if recent.search(u) else 1)
    detail_budget=max(0,min(int(source.get('detail_budget',4)),30))
    attempted=backlog[:detail_budget];backlog=backlog[detail_budget:]
    for url in attempted:
        try:
            slug=url.rsplit('/',1)[-1]
            item=metadata(get(PUBLIC+'coleccion/'+quote(slug)),publishers,source)
            found[canonical(item['detail_url'])]=item
        except Exception as exc:
            failures.append({'url':url,'error':str(exc)})
            backlog.append(url)
    state={'publisher_cursor':(cursor+budget)%len(ordered),'url_backlog':backlog,
        'sitemap_urls':listed,'manufacturers':[{'id':i,'name':publishers[i]} for i in ordered]}
    report={'name':source['name'],'type':'public_catalog_api','status':'ok',
        'collections_found':len(found),'manufacturers_found':len(publishers),
        'sitemap_entries':sitemap_count,'details_pending':len(backlog),
        'capped_queries':capped,'errors':failures,
        'coverage':'public_index_with_rotating_manufacturers_and_sitemap_backfill'}
    return list(found.values()),report,state
