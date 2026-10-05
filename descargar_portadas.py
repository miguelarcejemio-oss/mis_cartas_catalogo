#!/usr/bin/env python3
import json,os,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M=json.load(open(os.path.join(ROOT,"portadas","manifest.json"),encoding="utf-8"))
for item in M["items"]:
    if not item.get("source_url"): continue
    dest=os.path.join(ROOT,item["file"])
    os.makedirs(os.path.dirname(dest),exist_ok=True)
    try:
        req=urllib.request.Request(item["source_url"],headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=30) as r, open(dest,"wb") as f: f.write(r.read())
        item["local_file_present"]=True
        print("OK",item["id"])
    except Exception as e: print("ERROR",item["id"],e)
json.dump(M,open(os.path.join(ROOT,"portadas","manifest.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2)
