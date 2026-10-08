#!/usr/bin/env python3
"""Fetch, verify and append complete collections; never replace existing records."""
import argparse
import sys
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DISCOVERY = ROOT / 'portadas/descubrimiento.json'
OUTPUT = ROOT / 'portadas/enriquecimiento.json'
UA = 'MisCartasCatalog/1.0'
LEGAL = 'https://cromosrepes.com/ayuda/legal'


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def norm(value):
    return re.sub(r'\s+', ' ', str(value)).strip()


def identity(item):
    return norm(item.get('identity_key') or '|'.join(str(item.get(k, '')) for k in ('name', 'year', 'publisher'))).casefold()


class Blocked(Exception):
    def __init__(self, code, url, detail):
        self.code, self.url, self.detail = code, url, detail
        super().__init__(f'{code}: {detail} ({url})')


class Client:
    """Public requests only, obey robots, delays, size limits and auth walls."""
    def __init__(self):
        self.robots = {}
        self.last = {}
        self.cache = {}

    def raw(self, url):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise Blocked('unsafe_url', url, 'HTTPS público requerido')
        import ipaddress
        try:
            ipaddress.ip_address(parts.hostname)
        except ValueError:
            pass
        else:
            raise Blocked('unsafe_url', url, 'No se permiten direcciones IP')
        if parts.hostname == 'localhost' or parts.hostname.endswith(('.local', '.internal')):
            raise Blocked('unsafe_url', url, 'Destino local')
        try:
            with urlopen(Request(url, headers={'User-Agent': UA}), timeout=25) as response:
                final = response.geturl()
                if urlsplit(final).hostname != parts.hostname:
                    raise Blocked('redirect_host', url, final)
                if re.search(r'/(?:usuario/login|login|signin)(?:/|$)', urlsplit(final).path):
                    raise Blocked('login_required', url, final)
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise Blocked('response_too_large', url, '8 MB máximo')
                content_type = response.headers.get('Content-Type', '')
                if 'html' in content_type and b'document.location.href' in data and (b'noscript' in data or b'cookie' in data.lower()) and len(data) < 10000:
                    raise Blocked('javascript_cookie_challenge', url, 'HTTP 200 contiene una pantalla de JavaScript/cookies; no es la página solicitada')
                return final, content_type, data
        except HTTPError as exc:
            raise Blocked('http_error', url, f'HTTP {exc.code} {exc.reason}') from exc

    def fetch(self, url):
        if url in self.cache:
            return self.cache[url]
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            robots_url = origin + '/robots.txt'
            try:
                _, _, raw = self.raw(robots_url)
                parser = RobotFileParser()
                parser.parse(raw.decode('utf-8').splitlines())
            except Blocked as exc:
                if 'HTTP 404 ' not in exc.detail:
                    raise Blocked('robots_unavailable', robots_url, exc.detail) from exc
                parser = RobotFileParser(); parser.parse([])
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch(UA, url):
            raise Blocked('robots_disallow', url, 'robots.txt prohíbe esta ruta')
        delay = max(5, parser.crawl_delay(UA) or parser.crawl_delay('*') or 0)
        time.sleep(max(0, delay - (time.monotonic() - self.last.get(origin, 0))))
        try:
            result = self.raw(url)
        finally:
            self.last[origin] = time.monotonic()
        self.cache[url] = result
        return result


def parse_detail(raw, base):
    soup = BeautifulSoup(raw, 'html.parser')
    heading = soup.find('h1')
    if not heading:
        raise Blocked('empty_or_unrecognized_detail', base, f'{len(raw)} bytes; sin título de colección')
    title = heading.get_text(' ', strip=True)
    tables = []
    links, covers = [], []
    # Only collection description/metadata and explicitly labelled checklist tables.
    # Never parse collectors' faltas/repes, notes or user profiles.
    for table in soup.find_all('table'):
        rows = [[norm(c.get_text(' ', strip=True)) for c in tr.find_all(['th', 'td'], recursive=False)] for tr in table.find_all('tr')]
        if not rows:
            continue
        header = ' '.join(rows[0]).casefold()
        if any(x in header for x in ('usuario', 'faltas', 'repes', 'notas')):
            continue
        if any(x in header for x in ('descripción', 'descripcion', 'año', 'número', 'numero', 'nº', 'number')):
            tables.append(rows)
            for anchor in table.find_all('a', href=True):
                url = urljoin(base, anchor['href'])
                if urlsplit(url).scheme == 'https' and not re.search(r'/(usuario|mensajes|misdatos)/', url):
                    links.append({'url': url, 'label': anchor.get_text(' ', strip=True)})
            for img in table.find_all('img', src=True):
                label = norm(img.get('alt', '') + ' ' + img.get('title', ''))
                if re.search(r'portada|cover|álbum|album|archivador', label, re.I):
                    covers.append({'url': urljoin(base, img['src']), 'label': label})
    return {'title': title, 'tables': tables, 'links': links, 'covers': covers}


def parse_cards(detail):
    cards = []
    for rows in detail['tables']:
        if not rows:
            continue
        headers = [v.casefold() for v in rows[0]]
        def column(pattern):
            return next((i for i, h in enumerate(headers) if re.fullmatch(pattern, h)), None)
        number = column(r'número|numero|nº|number|no\.?')
        name = column(r'nombre|name|jugador|player|descripción|descripcion')
        if number is None or name is None:
            continue
        team = column(r'equipo|team'); section = column(r'serie|sección|seccion|section')
        for row in rows[1:]:
            if len(row) != len(headers) or not row[number] or not row[name]:
                raise ValueError('checklist_row_incomplete')
            cards.append({'n': row[number], 'player': row[name], 'team': row[team] if team is not None else '', 'section': row[section] if section is not None else ''})
    if not cards:
        raise ValueError('checklist_not_public: no hay tabla de números y nombres')
    numbers = [x['n'] for x in cards]
    if len(numbers) != len(set(numbers)):
        raise ValueError('duplicate_or_ambiguous_card_ids')
    return cards


def parse_pdf(data, item):
    """Conservative text adapter: explicit name, year, total and unique raw IDs."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError('encrypted_checklist')
    if len(reader.pages) > 100:
        raise ValueError('checklist_too_many_pages')
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    if norm(item['name']).casefold() not in norm(text).casefold() or str(item['year']) not in text:
        raise ValueError('pdf_collection_identity_not_verified')
    counts = re.findall(r'(?:total\s*(?:de\s*)?|consta de\s*)(\d+)\s*(?:cartas|cromos|cards|megafichas)', text, re.I)
    if len(set(counts)) != 1:
        raise ValueError('pdf_complete_count_not_verified')
    rows = [['Numero', 'Nombre']]
    for line in text.splitlines():
        match = re.fullmatch(r'\s*((?:[A-Z]{1,10}-)?\d{1,4}(?:[A-Za-z]|[ -]bis)?)\s+(.+?)\s*', line)
        if match:
            rows.append([match[1], norm(match[2])])
    # Preserve identifiers exactly; no inferred cards, gaps or fabricated sections.
    if len(rows) - 1 != int(counts[0]):
        raise ValueError('pdf_extraction_incomplete_or_ambiguous')
    return {'title': item['name'], 'tables': [rows, [['Descripcion'], [f'Total {counts[0]} cartas']]], 'links': [], 'covers': []}


def permission(url, config):
    host = urlsplit(url).hostname
    for entry in config.get('reuse_permissions', []):
        if entry.get('host') == host and entry.get('publication_allowed') is True and entry.get('evidence_url'):
            return entry
    return None


def verify_collection(item, client, config):
    url = item.get('detail_url')
    if not url:
        raise Blocked('missing_detail_url', '', 'No se inventa una URL de colección')
    final, initial_type, raw = client.fetch(url)
    if not raw.strip() and '/coleccion/ficha/' in url:
        # Public canonical description, not an attempt to bypass authentication.
        url = url.replace('/coleccion/ficha/', '/coleccion/cromos/', 1)
        final, _, raw = client.fetch(url)
    detail = parse_pdf(raw, item) if ('pdf' in initial_type or raw.startswith(b'%PDF-')) else parse_detail(raw, final)
    if norm(item['name']).casefold() not in norm(detail['title']).casefold():
        raise Blocked('identity_mismatch', final, 'Título distinto de la candidata')
    if str(item.get('year', '')) not in detail['title']:
        raise Blocked('identity_mismatch', final, 'Año no coincide')
    sources = [final] + [link['url'] for link in detail['links'] if re.search(r'checklist|lista.*(?:cartas|cromos)', link['label'], re.I)]
    blockers = []
    cards = None; checklist_url = None
    for source_url in sources:
        grant = permission(source_url, config)
        if not grant:
            blockers.append({'code': 'reuse_not_authorized', 'url': source_url, 'detail': 'No consta permiso de publicación; CromosRepes requiere permiso previo por escrito', 'terms_url': LEGAL})
            continue
        try:
            if source_url == final:
                candidate_detail = detail
            else:
                _, content_type, data = client.fetch(source_url)
                if 'pdf' in content_type or data.startswith(b'%PDF-'):
                    candidate_detail = parse_pdf(data, item)
                else:
                    candidate_detail = parse_detail(data, source_url)
                if norm(item['name']).casefold() not in norm(candidate_detail['title']).casefold():
                    raise ValueError('external_checklist_identity_mismatch')
            candidate_cards = parse_cards(candidate_detail)
            text = ' '.join(' '.join(row) for table in candidate_detail['tables'] for row in table)
            counts = re.findall(r'(?:total\s*(?:de\s*)?|consta de\s*)(\d+)\s*(?:cartas|cromos|cards|megafichas)', text, re.I)
            if len(set(counts)) != 1 or len(candidate_cards) != int(counts[0]):
                raise ValueError('complete_count_not_verified')
            cards, checklist_url = candidate_cards, source_url
            break
        except (ValueError, Blocked) as exc:
            blockers.append({'code': 'checklist_verification_failed', 'url': source_url, 'detail': str(exc)})
    cover_url = None; cover_bytes = None
    for cover in detail['covers']:
        if not permission(cover['url'], config):
            blockers.append({'code': 'cover_reuse_not_authorized', 'url': cover['url']})
            continue
        try:
            _, content_type, data = client.fetch(cover['url'])
            if not content_type.startswith('image/'):
                raise ValueError('cover_not_image')
            with Image.open(io.BytesIO(data)) as img:
                if img.width < 150 or img.height < 150:
                    raise ValueError('cover_too_small')
                img.verify()
            cover_url, cover_bytes = cover['url'], data
            break
        except (ValueError, OSError, Blocked) as exc:
            blockers.append({'code': 'cover_verification_failed', 'url': cover['url'], 'detail': str(exc)})
    if cards is None:
        return None, {'detail_url': final, 'cover_candidates': detail['covers'], 'checklist_candidates': [x for x in detail['links'] if re.search(r'checklist|lista.*(?:cartas|cromos)', x['label'], re.I)], 'blockers': blockers or [{'code': 'cover_and_checklist_not_public', 'url': final}]}
    cid = 'cr-' + hashlib.sha256(identity(item).encode()).hexdigest()[:24]
    filtered = [c for c in cards if not re.search(r'aut[oó]grafo original|original autograph|serial.numbered parallel', c['section'] + ' ' + c['player'], re.I)]
    if not filtered:
        raise ValueError('empty_checklist_after_policy')
    for card in filtered:
        card['original_identifier'] = card['n']
        card['id'] = cid + '-' + hashlib.sha256(card['n'].encode()).hexdigest()[:16]
    record = {'id': cid, 'name': item['name'], 'season': str(item['year']), 'brand': item['publisher'], 'cards': filtered, 'card_count': len(filtered), 'checklist_url': checklist_url, 'source_url': final, 'cover': cover_url, 'cover_url': cover_url, 'verification': {'source_card_count': len(cards), 'excluded_count': len(cards)-len(filtered), 'complete': True, 'permission_evidence': permission(checklist_url, config)['evidence_url'], 'cover_sha256': hashlib.sha256(cover_bytes).hexdigest() if cover_bytes else None}}
    return record, {'blockers': blockers}


def run(root=ROOT, limit=20, client=None):
    client = client or Client()
    discovery = load(root / 'portadas/descubrimiento.json', {})
    snapshot = load(root / 'portadas/discovery_snapshot.json', {})
    previous = load(root / 'portadas/enriquecimiento.json', {})
    config = load(root / 'fuentes.json', {})
    catalog = load(root / 'catalogo.json', {})
    queue = {}
    for item in previous.get('pending_review', []) + discovery.get('new_candidates', []) + discovery.get('changed_candidates', []) + snapshot.get('collections', []):
        if item.get('name') and item.get('detail_url'):
            queue[identity(item)] = {**queue.get(identity(item), {}), **item, 'last_checked': item.get('last_checked') or queue.get(identity(item), {}).get('last_checked')}
    known_urls = {x.get('source_url') for x in catalog['collections']}
    known_names = {norm(x['name']).casefold() for x in catalog['collections']}
    report = {'schema_version': 2, 'checked_at': datetime.now(timezone.utc).isoformat(), 'verified': [], 'pending_review': [], 'errors': [], 'published': [], 'attempted': 0}
    # Official targets also include existing collections; candidate-name dedup must not skip them.
    from scripts.official_checklists import verify_official, publish_existing
    report['official_checks'] = []
    for target in config.get('official_checklists', []):
        try:
            result, cards = verify_official(target, client, config)
            report['official_checks'].append(result)
            if publish_existing(catalog, target, cards, result):
                report['published'].append(target['collection_id'])
        except Exception as exc:
            report['official_checks'].append({'id': target['collection_id'], 'complete': False,
                'blockers': [{'code': getattr(exc, 'code', type(exc).__name__),
                'url': getattr(exc, 'url', target['checklist_url']), 'detail': str(exc)}]})
    from scripts.existing_collections import enrich_existing
    checks, updates, attempts = enrich_existing(catalog, list(queue.values()), config,
        client, previous, max(0, limit - report['attempted']))
    report['existing_checks'] = checks
    report['published'].extend(updates)
    report['attempted'] += attempts
    # Oldest checked first: bounded scheduled runs eventually retry the entire queue.
    candidates = sorted(queue.values(), key=lambda x: (x.get('last_checked') or '', identity(x)))
    for item in candidates:
        if item['detail_url'] in known_urls or norm(item['name']).casefold() in known_names:
            continue
        item = {k: v for k, v in item.items() if k not in ('blockers', 'verification_reason')}
        if report['attempted'] >= limit:
            report['pending_review'].append(item); continue
        report['attempted'] += 1
        item['last_checked'] = report['checked_at']
        try:
            record, evidence = verify_collection(item, client, config)
            item.update(evidence)
            if record:
                if record['id'] in {x['id'] for x in catalog['collections']}:
                    raise ValueError('collection_id_collision')
                catalog['collections'].append(record)
                known_names.add(norm(record['name']).casefold())
                known_urls.add(record['source_url'])
                report['verified'].append({'id': record['id'], 'source_url': record['source_url'], 'card_count': record['card_count']})
                report['published'].append(record['id'])
                continue
        except Blocked as exc:
            item['blockers'] = [{'code': exc.code, 'url': exc.url, 'detail': exc.detail}]
        except Exception as exc:
            error = {'code': type(exc).__name__, 'url': item['detail_url'], 'detail': str(exc)}
            item['blockers'] = [error]; report['errors'].append(error)
        item['enrichment_status'] = 'blocked' if item.get('blockers') else 'pending_verification'
        report['pending_review'].append(item)
    # No rewrite whatsoever if nothing was safely added. Existing IDs/cards/state untouched.
    if report['published']:
        save(root / 'catalogo.json', catalog)
    save(root / 'portadas/enriquecimiento.json', report)
    print(f"Enrichment: {report['attempted']} comprobadas, {len(report['published'])} publicadas, {len(report['pending_review'])} pendientes")
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    run(limit=max(0, args.limit))
