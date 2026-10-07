import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Safari/537.36"

UPDATES = Path("portadas/actualizaciones.json")
OUTPUT = Path("portadas/enrichment_results.json")

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}

def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def fetch(url, timeout=20):
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8"
        }
    )
    with urlopen(req, timeout=timeout) as response:
        return response.geturl(), response.headers.get("Content-Type", ""), response.read()

def collection_query(item):
    parts = [
        item.get("name", ""),
        item.get("publisher", ""),
        item.get("year", "")
    ]
    return " ".join(str(x).strip() for x in parts if str(x).strip())


def main():
    global UPDATES, OUTPUT
    UPDATES = "portadas/actualizaciones.json"
    OUTPUT = "portadas/enriquecimiento.json"
    data = load_json(UPDATES, {})
    candidates = data.get("new_candidates", [])
    changed = data.get("changed_candidates", [])

    results = {
        "schema_version": 1,
        "source": "CromosRepes",
        "total_candidates": len(candidates) + len(changed),
        "verified": [],
        "pending_review": [],
        "errors": []
    }

    for item in candidates + changed:
        record = dict(item)
        record.setdefault("cover_candidates", [])
        record.setdefault("checklist_candidates", [])
        record["enrichment_status"] = "pending_verification"
        record["verification_reason"] = (
            "Pendiente de comprobar portada y checklist "
            "mediante fuentes accesibles y autorizadas"
        )
        results["pending_review"].append(record)

    save_json(OUTPUT, results)

    print("Candidatas:", results["total_candidates"])
    print("Verificadas:", len(results["verified"]))
    print("Pendientes:", len(results["pending_review"]))
    print("Errores:", len(results["errors"]))
    print("Informe:", OUTPUT)


if __name__ == "__main__":
    main()
