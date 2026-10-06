#!/usr/bin/env python3
"""Mis Cartas: detector conservador de nuevas colecciones."""

import hashlib
import html
import json
import re
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

UA = "MisCartasCatalogBot/2.0"
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

            if source_type == "official_listing":

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

    core = {
        "schema_version": 2,
        "checked_sources": checked,
        "pending_review": pending,
        "publishable": [],
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
