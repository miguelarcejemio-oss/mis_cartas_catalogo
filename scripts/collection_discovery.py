UA="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36"
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
CATALOG=ROOT / "catalogo.json"
SOURCES=ROOT / "fuentes.json"
REPORT=ROOT / "portadas/descubrimiento.json"
SNAPSHOT=ROOT / "portadas/discovery_snapshot.json"
from html.parser import HTMLParser
def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def norm(v):
    return re.sub(r"\s+"," ",html.unescape(str(v or ""))).strip()

def key(v):
    return re.sub(r"[^\w]+"," ",norm(v).lower()).strip()

def load(p,d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return d

def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def fetch(url):
    q=Request(url,headers={"User-Agent":UA,"Accept-Language":"es-ES,es;q=0.9"})
    with urlopen(q,timeout=30) as r:
        raw=r.read(8000001)
        if len(raw)>8000000:
            raise ValueError("respuesta demasiado grande")
        charset=r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset,errors="replace"),r.geturl()

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]; self.tr=False; self.td=False
        self.cells=[]; self.links=[]; self.txt=[]; self.clinks=[]
        self.href=None; self.atxt=[]

    def handle_starttag(self,t,a):
        a=dict(a); t=t.lower()
        if t=="tr":
            self.tr=True; self.cells=[]; self.links=[]
        elif self.tr and t in ("td","th"):
            self.td=True; self.txt=[]; self.clinks=[]
        elif self.td and t=="a":
            self.href=a.get("href"); self.atxt=[]

    def handle_data(self,d):
        if self.td: self.txt.append(d)
        if self.href is not None: self.atxt.append(d)

    def handle_endtag(self,t):
        t=t.lower()
        if t=="a" and self.href is not None:
            self.clinks.append((self.href,norm(" ".join(self.atxt))))
            self.href=None
        elif t in ("td","th") and self.td:
            self.cells.append(norm(" ".join(self.txt)))
            self.links.append(list(self.clinks)); self.td=False
        elif t=="tr" and self.tr:
            if self.cells: self.rows.append((list(self.cells),list(self.links)))
            self.tr=False

def parse_index(page,base,source):
    parser=Tables(); parser.feed(page); out={}
    for cells,links in parser.rows:
        if len(cells)<3:
            continue
        name,year,publisher=cells[:3]
        if not name or not re.fullmatch(r"\d{4}",year or ""):
            continue
        detail=None
        if links and links[0]:
            detail=urljoin(base,links[0][0][0])
        identity=key(f"{name}|{year}|{publisher}")
        seed=f"{source[chr(110)+chr(97)+chr(109)+chr(101)]}|{identity}|{detail or chr(32)}"
        sid=hashlib.sha256(seed.encode()).hexdigest()[:24]
        out[identity]={"stable_id":sid,"identity_key":identity,"name":name,"year":year,"publisher":publisher or "Desconocida","source_name":source.get("name",""),"source_url":base,"detail_url":detail,"status":"discovered","checklist_status":"not_verified","cover_status":"not_verified"}
    return list(out.values())

class RecentLinks(HTMLParser):
    """Read collection links only; never collectors, messages or inventories."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href=None; self.words=[]; self.items=[]

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href=dict(attrs).get('href'); self.words=[]

    def handle_data(self, data):
        if self.href: self.words.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            if re.search(r'/coleccion/(?:ficha|cromos)/[^/?#]+$', self.href):
                self.items.append((self.href, norm(' '.join(self.words))))
            self.href=None

def parse_recent(page, base, source):
    parser=RecentLinks(); parser.feed(page); out={}
    for href, name in parser.items:
        detail=urljoin(base,href)
        if not name or not detail.startswith('https://cromosrepes.com/coleccion/'):
            continue
        # This feed supplies no publication year or manufacturer. Do not guess them
        # from the product name (a 2027 edition may have been released in 2026).
        identity='url:'+detail.replace('/coleccion/cromos/','/coleccion/ficha/')
        out[identity]={'stable_id':hashlib.sha256(identity.encode()).hexdigest()[:24],
            'identity_key':identity,'name':name,'year':'','publisher':'Desconocida',
            'source_name':source['name'],'source_url':base,'detail_url':detail,
            'status':'discovered','checklist_status':'not_verified',
            'cover_status':'not_verified','metadata_status':'pending',
            'discovery_priority':1}
    return list(out.values())

def known_signatures(cat):
    out=set()
    collections=cat.get("collections",[]) if isinstance(cat,dict) else []
    for c in collections:
        if not isinstance(c,dict):
            continue
        name=c.get("name") or c.get("title") or ""
        year=c.get("year") or c.get("season") or ""
        publisher=c.get("publisher") or c.get("manufacturer") or c.get("brand") or ""
        if name:
            out.add("name:"+key(name))
        out.add(key(f"{name}|{year}|{publisher}"))
    return out

def enrich_defaults(item):
    item.setdefault("cover_candidates", [])
    item.setdefault("checklist_candidates", [])
    item.setdefault("detail_status", "pending")
    item.setdefault("last_checked", None)
    item.setdefault("fingerprint", None)
    return item


def run():
    cfg=load(SOURCES,{}) or {}
    cat=load(CATALOG,{}) or {}
    old=load(SNAPSHOT,{}) or {}
    oldmap={x.get("identity_key"):x for x in old.get("collections",[]) if isinstance(x,dict)}
    source_state=dict(old.get('source_state',{}))
    known=known_signatures(cat)
    found={}; checked=[]; errors=[]
    sources=(cfg.get("discovery_sources",[]) or [])+(cfg.get("sources",[]) or [])

    for source in sources:
        if not isinstance(source,dict) or not source.get("enabled",True):
            continue
        kind=source.get('type')
        if kind not in ('catalog_index','recent_collections','tracked_collections','public_catalog_api'):
            checked.append({"name":source.get("name",source.get("url","")),"type":source.get("type"),"status":"reserved_for_verification"})
            continue
        try:
            public_report=None
            if kind == 'public_catalog_api':
                from scripts.discovery_public import run as public_discovery
                from scripts.enrich_collections import Client
                items,public_report,state=public_discovery(source,source_state.get(source['url'],{}),
                    [x.get('detail_url') for x in oldmap.values()],Client())
                source_state[source['url']]=state
                items=[enrich_defaults(x) for x in items]
                errors.extend({'source':source['name'],**error} for error in public_report['errors'])
            elif kind == 'tracked_collections':
                items=[enrich_defaults({**x,'source_name':source['name'],
                    'source_url':source.get('url',''),'status':'discovered',
                    'checklist_status':'not_verified','cover_status':'not_verified',
                    'identity_key':key(f"{x['name']}|{x['year']}|{x['publisher']}"),
                    'discovery_priority':0}) for x in source.get('collections',[])]
                for item in items:
                    item.setdefault('stable_id',hashlib.sha256(item['identity_key'].encode()).hexdigest()[:24])
            else:
                page,final=fetch(source["url"])
                parser=parse_recent if kind == 'recent_collections' else parse_index
                items=[enrich_defaults(x) for x in parser(page,final,source)]
            if not items:
                raise ValueError('empty_or_unrecognized_source: no se encontraron colecciones')
            for item in items:
                found[item["identity_key"]]=item
            checked.append(public_report or {"name":source["name"],"type":kind,"status":"ok","collections_found":len(items),
                'coverage':source.get('coverage','partial')})
        except Exception as error:
            errors.append({"source":source.get("name"),"url":source.get("url"),"error":f"{type(error).__name__}: {error}"})
            checked.append({"name":source.get("name"),"type":kind,"status":"error"})

    seen=set(found)
    # The same collection may occur in both the popularity table and recent feed.
    by_url={x.get('detail_url','').replace('/coleccion/cromos/','/coleccion/ficha/'):i
        for i,x in found.items() if not i.startswith('url:')}
    for identity,item in list(found.items()):
        target=by_url.get(item.get('detail_url','').replace('/coleccion/cromos/','/coleccion/ficha/'))
        if identity.startswith('url:') and target:
            found[target]['discovery_priority']=min(found[target].get('discovery_priority',2),1)
            del found[identity]; seen.discard(identity)
    # A temporary outage must not erase previously discovered candidates.
    for identity, prior in oldmap.items():
        if identity not in found:
            found[identity]=prior
    # A formerly unknown year or manufacturer may later become known. The same
    # public collection URL is one candidate, regardless of those corrections.
    from scripts.discovery_public import canonical
    unique={};without_url={}
    for identity,item in found.items():
        url=canonical(item.get('detail_url'))
        if not url:
            without_url[identity]=item;continue
        previous=unique.get(url)
        rank=(identity in seen,bool(item.get('year')),item.get('publisher')!='Desconocida')
        if previous is None or rank>previous[0]:unique[url]=(rank,identity,item)
    found={**without_url,**{identity:item for _,identity,item in unique.values()}}
    rows=[]; new=[]; changed=[]
    stamp=now()
    for identity,item in sorted(found.items()):
        prior=oldmap.get(identity)
        item["last_seen"]=stamp if identity in seen else prior.get('last_seen')
        item["first_seen"]=prior.get("first_seen",stamp) if prior else stamp
        if prior:
            before=(prior.get("name"),prior.get("year"),prior.get("publisher"),prior.get("detail_url"))
            after=(item.get("name"),item.get("year"),item.get("publisher"),item.get("detail_url"))
            if before!=after:
                changed.append(dict(item))
        elif identity not in known and "name:"+key(item["name"]) not in known:
            new.append(dict(item))
        rows.append(item)

    snapshot={"schema_version":2,"updated_at":stamp,"collections":rows,'source_state':source_state}
    report={"schema_version":5,"checked_sources":checked,"new_candidates":new,"changed_candidates":changed,"pending_review":new+changed,"publishable":[],"errors":errors,"policy":{"auto_publish_unverified_checklists":False,"copy_social_data":False,"require_numeric_1_to_n":False,"preserve_raw_card_ids":True}}
    save(SNAPSHOT,snapshot)
    save(REPORT,{"checked_at":stamp,**report})
    print(f"CollectionDiscovery: {len(rows)} descubiertas | {len(new)} nuevas | {len(changed)} cambiadas | {len(errors)} errores")
    # A successful HTTP request with a changed layout is not successful discovery.
    return 0 if any(x.get('status')=='ok' and x.get('type')!='tracked_collections' for x in checked) else 1

if __name__=="__main__":
    raise SystemExit(run())
