UA="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36"
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
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
    known=known_signatures(cat)
    found={}; checked=[]; errors=[]
    sources=(cfg.get("discovery_sources",[]) or [])+(cfg.get("sources",[]) or [])

    for source in sources:
        if not isinstance(source,dict) or not source.get("enabled",True):
            continue
        if source.get("type")!="catalog_index":
            checked.append({"name":source.get("name",source.get("url","")),"type":source.get("type"),"status":"reserved_for_verification"})
            continue
        try:
            page,final=fetch(source["url"])
            items=[enrich_defaults(x) for x in parse_index(page,final,source)]
            for item in items:
                found[item["identity_key"]]=item
            checked.append({"name":source["name"],"type":"catalog_index","status":"ok","collections_found":len(items)})
        except Exception as error:
            errors.append({"source":source.get("name"),"url":source.get("url"),"error":f"{type(error).__name__}: {error}"})
            checked.append({"name":source.get("name"),"type":"catalog_index","status":"error"})

    # A temporary outage must not erase previously discovered candidates.
    for identity, prior in oldmap.items():
        if identity not in found:
            found[identity]=prior
    rows=[]; new=[]; changed=[]
    stamp=now()
    for identity,item in sorted(found.items()):
        prior=oldmap.get(identity)
        item["last_seen"]=stamp
        item["first_seen"]=prior.get("first_seen",stamp) if prior else stamp
        if prior:
            before=(prior.get("name"),prior.get("year"),prior.get("publisher"),prior.get("detail_url"))
            after=(item.get("name"),item.get("year"),item.get("publisher"),item.get("detail_url"))
            if before!=after:
                changed.append(dict(item))
        elif identity not in known and "name:"+key(item["name"]) not in known:
            new.append(dict(item))
        rows.append(item)

    snapshot={"schema_version":1,"updated_at":stamp,"collections":rows}
    report={"schema_version":5,"checked_sources":checked,"new_candidates":new,"changed_candidates":changed,"pending_review":new+changed,"publishable":[],"errors":errors,"policy":{"auto_publish_unverified_checklists":False,"copy_social_data":False,"require_numeric_1_to_n":False,"preserve_raw_card_ids":True}}
    save(SNAPSHOT,snapshot)
    save(REPORT,{"checked_at":stamp,**report})
    print(f"CollectionDiscovery: {len(rows)} descubiertas | {len(new)} nuevas | {len(changed)} cambiadas | {len(errors)} errores")
    return 0

if __name__=="__main__":
    raise SystemExit(run())
