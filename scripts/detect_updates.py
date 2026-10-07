#!/usr/bin/env python3
"""Mis Cartas: detector conservador de nuevas colecciones."""

import hashlib
import html
import json
import re
import io
from collections import defaultdict
from pypdf import PdfReader
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalogo.json"
SOURCES = ROOT / "fuentes.json"
REPORT = ROOT / "portadas" / "actualizaciones.json"

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
TIMEOUT = 25
MAX_BYTES = 4_000_000

CARD_TERMS = (
    "card", "cards", "trading", "collection", "coleccion", "colección",
    "album", "álbum", "sticker", "cromos", "megacracks",
    "adrenalyn", "flagship", "match attax"
)

FOOT_TERMS = (
    "football", "futbol", "fútbol", "laliga", "premier league",
    "champions league", "uefa", "fifa", "soccer", "liga"
)

NOISE = (
    "login", "account", "cart", "basket", "contact", "privacy",
    "terms", "cookies", "faq", "shipping", "wishlist", "search",
    "customer", "instagram", "facebook", "youtube", "tiktok"
)


def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def normtext(value):
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or "")).lower()
    ).strip()


def normurl(value):
    try:
        parts = urlsplit(str(value).strip())
    except Exception:
        return str(value).strip()

    if parts.scheme not in ("http", "https"):
        return str(value).strip()

    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gclid", "fbclid", "ref", "source"}
    ]

    path = re.sub(r"/{2,}", "/", parts.path or "/")

    if path != "/":
        path = path.rstrip("/")

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query),
            "",
        )
    )


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        },
    )

    with urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(MAX_BYTES + 1)

        if len(raw) > MAX_BYTES:
            raise ValueError("respuesta demasiado grande")

        charset = response.headers.get_content_charset() or "utf-8"

        return (
            raw.decode(charset, errors="replace"),
            response.geturl(),
        )


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.href = None
        self.txt = []
        self.attrs = {}

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.attrs = {
                key.lower(): (value or "")
                for key, value in attrs
            }
            self.href = self.attrs.get("href")
            self.txt = []

    def handle_data(self, data):
        if self.href is not None:
            self.txt.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            label = " ".join(
                self.txt
                + [
                    self.attrs.get("title", ""),
                    self.attrs.get("aria-label", ""),
                ]
            ).strip()

            self.out.append((self.href, label))

            self.href = None
            self.txt = []
            self.attrs = {}


def score(url, label):
    haystack = normtext(url + " " + label)

    if any(term in haystack for term in NOISE):
        return -10

    points = 0

    points += 2 * sum(
        term in haystack for term in CARD_TERMS
    )

    points += 2 * sum(
        term in haystack for term in FOOT_TERMS
    )

    if "/products/" in url or "/product/" in url:
        points += 2

    if re.search(
        r"\b20\d{2}[/_-]?\d{2,4}\b|\b\d{2}[/_-]\d{2}\b",
        haystack,
    ):
        points += 1

    return points


def extract(page, base, source):
    parser = Links()
    parser.feed(page)

    found = {}
    brand = str(source.get("brand") or "").strip()

    for href, label in parser.out:

        if not href:
            continue

        if href.startswith(
            ("#", "mailto:", "tel:", "javascript:")
        ):
            continue

        url = normurl(urljoin(base, href))

        if not url.startswith(("http://", "https://")):
            continue

        points = score(url, label)

        if points < 3:
            continue

        candidate = {
            "url": url,
            "name_hint": label[:240],
            "manufacturer_hint": brand,
            "score": points,
        }

        if (
            url not in found
            or points > found[url]["score"]
        ):
            found[url] = candidate

    return sorted(
        found.values(),
        key=lambda item: (-item["score"], item["url"]),
    )[:250]


def signatures(catalog):
    urls = set()
    names = set()

    collections = (
        catalog.get("collections", [])
        if isinstance(catalog, dict)
        else []
    )

    if not isinstance(collections, list):
        collections = []

    for collection in collections:

        if not isinstance(collection, dict):
            continue

        for key in (
            "url",
            "source_url",
            "official_url",
            "product_url",
        ):
            value = collection.get(key)

            if (
                isinstance(value, str)
                and value.startswith(("http://", "https://"))
            ):
                urls.add(normurl(value))

        name = (
            collection.get("name")
            or collection.get("title")
        )

        if name:
            names.add(normtext(name))

    return urls, names


def known(candidate, urls, names):

    if candidate["url"] in urls:
        return True

    hint = normtext(
        candidate.get("name_hint", "")
    )

    if len(hint) < 8:
        return False

    return any(
        len(name) >= 8
        and (
            hint in name
            or name in hint
        )
        for name in names
    )



PRODUCT_WORDS = (
    "starter pack", "starterpack", "multipack", "multi pack",
    "display", "booster", "blaster", "hobby box", "box",
    "caja", "sobre", "sobres", "pack", "packs",
    "album", "álbum", "binder", "carpeta",
    "lata", "tin", "bundle", "megapack"
)

TECHNICAL_TEXT = (
    "width:", "height:", "display:", "font-size:",
    "margin:", "padding:", "background:", "{", "}",
    "@media", "javascript:", "<style", "</style"
)


def clean_candidate_name(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -|:/")

    low = value.lower()

    if not value:
        return ""

    if any(token in low for token in TECHNICAL_TEXT):
        return ""

    if len(value) > 180:
        return ""

    return value


def collection_key(candidate):
    name = clean_candidate_name(
        candidate.get("name_hint", "")
    )

    if not name:
        name = candidate.get("url", "")

    key = normtext(name)

    for word in PRODUCT_WORDS:
        key = re.sub(
            r"\b" + re.escape(word) + r"\b",
            " ",
            key,
            flags=re.I,
        )

    # Quita precios y cantidades comerciales, pero conserva años/temporadas.
    key = re.sub(r"\b\d+\s*(sobres?|packs?|cards?|cromos?)\b", " ", key)
    key = re.sub(r"\b\d+[,.]\d{2}\s*€?\b", " ", key)
    key = re.sub(r"\s+", " ", key).strip(" -|:/")

    return key


def group_candidates(items):
    groups = {}

    for item in items:
        item = dict(item)

        cleaned = clean_candidate_name(
            item.get("name_hint", "")
        )

        if not cleaned:
            continue

        item["name_hint"] = cleaned
        key = collection_key(item)

        if len(key) < 4:
            continue

        if key not in groups:
            groups[key] = {
                **item,
                "collection_key": key,
                "evidence_urls": [item.get("url")],
                "variants": [cleaned],
            }
            continue

        group = groups[key]

        url = item.get("url")
        if url and url not in group["evidence_urls"]:
            group["evidence_urls"].append(url)

        if cleaned not in group["variants"]:
            group["variants"].append(cleaned)

        if item.get("score", 0) > group.get("score", 0):
            keep_urls = group["evidence_urls"]
            keep_variants = group["variants"]
            group.update(item)
            group["collection_key"] = key
            group["evidence_urls"] = keep_urls
            group["variants"] = keep_variants

    return sorted(
        groups.values(),
        key=lambda x: (-x.get("score", 0), x["collection_key"])
    )


CHECKLIST_TERMS = (
    "checklist", "check list", "lista de cartas",
    "lista de cromos", "card list", "set list",
    "lista completa", "colección completa"
)

COVER_TERMS = (
    "cover", "portada", "album", "álbum",
    "binder", "starter"
)


def extract_cover(page, base_url):
    patterns = (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
    )

    covers = []

    for pattern in patterns:
        for value in re.findall(pattern, page, flags=re.I):
            url = normurl(urljoin(base_url, html.unescape(value)))
            if url.startswith(("http://","https://")) and url not in covers:
                covers.append(url)

    return covers[:10]



def validate_checklist_structure(raw):
    """
    Segunda barrera:
    extrae numero + texto y exige numeracion coherente.
    Cualquier numero asociado a textos diferentes bloquea la publicacion.
    """
    try:
        reader = PdfReader(io.BytesIO(raw))
        cards = defaultdict(set)

        for page in reader.pages:
            text = page.extract_text() or ""

            for line in text.splitlines():
                line = re.sub(r"\s+", " ", line).strip()

                match = re.match(r"^(\d{1,4})\s+(.+)$", line)
                if not match:
                    continue

                number = int(match.group(1))
                description = match.group(2).strip()

                if description:
                    cards[number].add(description)

        if not cards:
            return {
                "structure_validated": False,
                "structure_error": "no_card_records",
                "structured_card_count": 0,
                "conflict_count": 0,
                "gap_count": 0,
            }

        numbers = sorted(cards)
        conflicts = {
            number: values
            for number, values in cards.items()
            if len(values) > 1
        }

        expected = set(range(numbers[0], numbers[-1] + 1))
        gaps = sorted(expected - set(numbers))

        valid = (
            numbers[0] == 1
            and len(cards) >= 20
            and not conflicts
            and not gaps
        )

        return {
            "structure_validated": valid,
            "structure_error": None if valid else "structural_conflict",
            "structured_card_count": len(cards),
            "first_card_number": numbers[0],
            "last_card_number": numbers[-1],
            "conflict_count": len(conflicts),
            "gap_count": len(gaps),
        }

    except Exception as error:
        return {
            "structure_validated": False,
            "structure_error": f"{type(error).__name__}: {error}",
            "structured_card_count": 0,
            "conflict_count": 0,
            "gap_count": 0,
        }


def validate_checklist_pdf(url):
    """Comprobación conservadora de que el PDF parece una checklist real."""
    try:
        request = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/pdf,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            },
        )

        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)

        if len(raw) > MAX_BYTES:
            raise ValueError("PDF demasiado grande")

        # Primera barrera: debe ser realmente un PDF.
        if not raw.startswith(b"%PDF"):
            return {
                "validated": False,
                "validation_error": "not_a_pdf",
            }

        # Extraemos cadenas visibles del PDF como validación preliminar.
        # La extracción completa de cartas se hará en la siguiente fase.
        visible = re.findall(rb"[\x20-\x7e]{4,}", raw)
        text = normtext(
            " ".join(
                x.decode("latin-1", errors="ignore")
                for x in visible
            )
        )

        terms = (
            "checklist", "card", "cards",
            "cromo", "cromos", "player",
            "jugador", "collection", "coleccion"
        )

        term_hits = sum(term in text for term in terms)
        number_hits = len(
            re.findall(r"(?<!\d)\d{1,4}(?!\d)", text)
        )

        preliminary_validated = term_hits >= 2 and number_hits >= 20

        structure = validate_checklist_structure(raw)

        validated = (
            preliminary_validated
            and structure.get("structure_validated", False)
        )

        return {
            "validated": validated,
            "validation_error": (
                None if validated
                else "content_not_checklist_like"
            ),
            "checklist_term_hits": term_hits,
            "number_hits": number_hits,
            **structure,
        }

    except Exception as error:
        return {
            "validated": False,
            "validation_error":
                f"{type(error).__name__}: {error}",
        }


def extract_checklists(page, base_url):
    parser = Links()
    parser.feed(page)

    found = []
    seen = set()

    for href, label in parser.out:
        if not href:
            continue

        url = normurl(urljoin(base_url, href))
        text = normtext(label + " " + href)

        checklist = any(
            term in text
            for term in CHECKLIST_TERMS
        )

        pdf = (
            url.lower().split("?")[0].endswith(".pdf")
            and any(term in text for term in (
                "card", "cards", "cromo", "cromos",
                "lista", "list", "set", "collection",
                "coleccion", "colección"
            ))
        )

        if (checklist or pdf) and url not in seen:
            seen.add(url)
            item = {
                "url": url,
                "label": clean_candidate_name(label),
                "type": "pdf" if pdf else "checklist_link"
            }

            if pdf:
                item.update(validate_checklist_pdf(url))
            else:
                item["validated"] = False
                item["validation_error"] = "link_not_pdf"

            found.append(item)

    return found[:20]

def ensure_candidate_name(candidate):
    candidate = dict(candidate)

    if candidate.get("name") or candidate.get("title"):
        return candidate

    url = candidate.get("url") or ""
    if not url:
        urls = candidate.get("evidence_urls") or []
        url = urls[0] if urls else ""

    slug = urlsplit(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()

    if slug:
        candidate["name"] = slug.title()

    return candidate

def enrich_candidate(candidate):
    candidate=ensure_candidate_name(candidate)

    if not candidate.get("name"):
        candidate["identity_valid"] = False
        candidate["publication_blocked"] = "missing_identity"
    else:
        candidate["identity_valid"] = True
    covers=[]
    checklists=[]
    inspected=[]

    for url in candidate.get("evidence_urls",[])[:4]:
        try:
            page, final_url=fetch(url)

            for cover in extract_cover(page,final_url):
                if cover not in covers:
                    covers.append(cover)

            for item in extract_checklists(page,final_url):
                if not any(x["url"]==item["url"] for x in checklists):
                    checklists.append(item)

            inspected.append({"url":final_url,"status":"ok"})

        except Exception as error:
            inspected.append({
                "url":url,
                "status":"unavailable",
                "detail":f"{type(error).__name__}: {error}"
            })

    candidate["cover_candidates"]=covers[:10]
    candidate["checklist_candidates"]=checklists[:20]
    candidate["inspected_evidence"]=inspected
    return candidate


def enrich_candidates(items):
    return [enrich_candidate(x) for x in items]

def publication_status(candidate):
    reasons=[]

    if not candidate.get("identity_valid", bool(candidate.get("name"))):
        reasons.append("missing_identity")

    if not candidate.get("cover_candidates"):
        reasons.append("missing_cover")

    checklists = candidate.get("checklist_candidates") or []

    if not checklists:
        reasons.append("missing_checklist")
    elif not any(
        item.get("validated")
        for item in checklists
    ):
        reasons.append("unvalidated_checklist")

    candidate["publication_ready"] = not reasons
    candidate["publication_blockers"] = reasons
    return candidate


def classify_publication(items):
    return [publication_status(dict(item)) for item in items]

def analyse_evidence(candidate):
    """Clasifica las evidencias sin inventar datos."""
    urls = candidate.get("evidence_urls", [])
    variants = candidate.get("variants", [])

    text = normtext(
        " ".join(variants) + " " + " ".join(urls)
    )

    checklist_hits = [
        term for term in CHECKLIST_TERMS
        if term in text
    ]

    cover_hits = [
        term for term in COVER_TERMS
        if term in text
    ]

    candidate["verification"] = {
        "identity": bool(candidate.get("collection_key")),
        "source_count": len(set(urls)),
        "cover_evidence": bool(cover_hits),
        "checklist_evidence": bool(checklist_hits),
        "cover_terms": cover_hits,
        "checklist_terms": checklist_hits,
    }

    # Una mención comercial NO basta para publicar.
    candidate["verification_score"] = (
        (2 if candidate["verification"]["identity"] else 0)
        + min(candidate["verification"]["source_count"], 2)
        + (2 if cover_hits else 0)
        + (3 if checklist_hits else 0)
    )

    # De momento ningún candidato descubierto se publica
    # sin haber extraído y validado realmente su checklist.
    candidate["status"] = "pending_review"
    candidate["reason"] = (
        "Pendiente de verificar portada y checklist"
    )

    return candidate


def verify_candidates(items):
    return [
        analyse_evidence(item)
        for item in items
    ]

def main():

    try:
        catalog = load(CATALOG)
        config = load(SOURCES)

    except Exception as error:
        print(
            "ERROR cargando configuración:",
            error,
            file=sys.stderr,
        )
        return 2

    known_urls, known_names = signatures(catalog)

    pending = []
    errors = []
    checked = []
    seen = set()

    sources = []

    for key in ("sources", "discovery_sources"):

        value = (
            config.get(key, [])
            if isinstance(config, dict)
            else []
        )

        if isinstance(value, list):
            sources.extend(value)

    for source in sources:

        if not isinstance(source, dict):
            continue

        if not source.get("enabled", True):
            continue

        if not source.get("url"):
            continue

        name = str(
            source.get("name")
            or source["url"]
        )

        source_type = str(
            source.get("type")
            or "official_html"
        )

        try:

            page, final_url = fetch(
                str(source["url"])
            )

            digest = hashlib.sha256(
                page.encode(
                    "utf-8",
                    errors="replace",
                )
            ).hexdigest()

            if source_type in ("official_listing", "listing"):

                candidates = extract(
                    page,
                    final_url,
                    source,
                )

                new_count = 0

                for candidate in candidates:

                    if candidate["url"] in seen:
                        continue

                    seen.add(candidate["url"])

                    if known(
                        candidate,
                        known_urls,
                        known_names,
                    ):
                        continue

                    candidate.update(
                        status="pending_review",
                        reason=(
                            "Candidato: portada y checklist "
                            "aún no verificadas"
                        ),
                        source=name,
                    )

                    pending.append(candidate)
                    new_count += 1

                checked.append(
                    {
                        "name": name,
                        "type": source_type,
                        "status": "ok",
                        "links_considered": len(candidates),
                        "new_candidates": new_count,
                        "fingerprint": digest,
                    }
                )

            else:

                checked.append(
                    {
                        "name": name,
                        "type": source_type,
                        "status": "ok",
                        "fingerprint": digest,
                    }
                )

        except Exception as error:

            errors.append(
                {
                    "source": name,
                    "url": str(source["url"]),
                    "error": (
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                }
            )

            checked.append(
                {
                    "name": name,
                    "type": source_type,
                    "status": "error",
                }
            )

    pending = group_candidates(pending)
    pending = enrich_candidates(pending)
    pending = verify_candidates(pending)
    pending = classify_publication(pending)

    publishable = [
        item for item in pending
        if item.get("publication_ready")
    ]

    pending_review = [
        item for item in pending
        if not item.get("publication_ready")
    ]

    core = {
        "schema_version": 4,
        "checked_sources": checked,
        "pending_review": pending_review,
        "publishable": publishable,
        "errors": errors,
    }

    old_core = None

    if REPORT.exists():

        try:
            old = load(REPORT)

            if isinstance(old, dict):
                old_core = {
                    key: old.get(key)
                    for key in core
                }

        except Exception:
            pass

    changed = old_core != core

    if changed:

        REPORT.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        report = {
            "checked_at": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            **core,
        }

        REPORT.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        f"Fuentes: {len(checked)} | "
        f"candidatos: {len(pending)} | "
        f"errores: {len(errors)} | "
        "informe modificado: "
        f"{'sí' if changed else 'no'}"
    )

    for error in errors:
        print(
            f"AVISO {error['source']}: "
            f"{error['error']}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
