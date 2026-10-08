"""Official Panini readers. A successful download is not a reuse licence."""
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from pypdf import PdfReader

SECTIONS = {'ELITE', 'VÉRTIGO', 'ZONA VIP', 'MÁSTER ROOKIE', 'MASTER ROOKIE',
            'FLASHBACK', 'FLASHBACK ANTHOLOGY', 'CARD MEGAPOWER',
            'NUEVOS FICHAJES', 'ELITE POWER', 'VÉRTIGO POWER', 'ZONA VIP POWER',
            'CARDS ÍNDICE'}
TEAMS = {'DEPORTIVO ALAVÉS', 'ATHLETIC CLUB', 'ATLÉTICO DE MADRID',
         'FC BARCELONA', 'BARCELONA', 'REAL BETIS', 'BETIS', 'CELTA',
         'CELTA DE VIGO', 'ELCHE', 'RCD ESPANYOL', 'ESPANYOL', 'GETAFE',
         'GETAFE CF', 'GIRONA FC', 'LEVANTE UD', 'GIRONA', 'LEVANTE', 'MALLORCA', 'CA OSASUNA', 'OSASUNA',
         'REAL OVIEDO', 'OVIEDO', 'RAYO VALLECANO', 'REAL MADRID',
         'REAL SOCIEDAD', 'SEVILLA', 'VALENCIA', 'VILLARREAL'}


def identifier(value):
    value = re.sub(r'\s+', ' ', str(value).strip().upper())
    match = re.fullmatch(r'(P?)(\d+)(?:\s*(BIS))?', value)
    if match:
        return match[1] + str(int(match[2])) + (' BIS' if match[3] else '')
    return value


def shop_rows(raw):
    """Read the manufacturer's structured checklist, not user tables or stock counts."""
    soup = BeautifulSoup(raw, 'html.parser')
    for script in soup.find_all('script', type='text/x-magento-init'):
        config = json.loads(script.string or script.get_text())
        for value in config.values():
            components = value.get('Magento_Ui/js/core/app', {}).get('components', {})
            rows = components.get('missing_stickers', {}).get('missingStickers')
            if rows is not None:
                result = {}
                for row in rows:
                    key = identifier(row['identifier'])
                    if key in result:
                        raise ValueError('duplicate_shop_identifier:' + key)
                    result[key] = row
                if not result:
                    raise ValueError('empty_official_checklist')
                return result
    raise ValueError('official_checklist_missing_or_javascript_challenge')


def pdf_rows(raw):
    reader = PdfReader(io.BytesIO(raw))
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    if 'NUEVOS FICHAJES' not in text or 'SPECIAL ONE BLACK' not in text:
        raise ValueError('wrong_checklist_document')
    cards, section, team, excluded = [], '', '', 0
    autograph = False
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if not line or re.fullmatch(r'2ª edición 3ª edición', line):
            continue
        if line == 'AUTÓGRAFOS':
            autograph = True
            continue
        if line in SECTIONS:
            section, team, autograph = line.replace('MASTER ROOKIE', 'MÁSTER ROOKIE'), '', False
            continue
        if line.startswith('SPECIAL ONE '):
            section, team = line.split(' (')[0], ''
            continue
        if line in TEAMS:
            section, team = 'Base', line
            continue
        if line in {'CARDS POWER (PARALLELS)', 'INSERTS'}:
            continue
        if autograph:
            if not re.match(r'\d+ autógrafos', line):
                excluded += 1
            continue
        match = re.match(r'^(P?\d+(?: BIS)?|IN\d+)\s+(.+)$', line)
        if match:
            number, name = match.groups()
            original = number
        elif section in {'SPECIAL ONE BLACK', 'SPECIAL ONE GOLD'}:
            number, original, name = None, None, line
        elif cards and section in {'FLASHBACK ANTHOLOGY', 'CARD MEGAPOWER'}:
            cards[-1]['player'] += ' ' + line
            continue
        else:
            raise ValueError('unrecognised_checklist_line:' + line)
        club = re.search(r'\s*\(([^)]+)\)$', name)
        if club:
            name, card_team = name[:club.start()].strip(), club[1]
        else:
            card_team = team
        key = identifier(number) if number else section + ':' + name
        cards.append({'key': key, 'original_identifier': original, 'n': number,
                      'player': name, 'team': card_team, 'section': section})
    if len({card['key'] for card in cards}) != len(cards):
        raise ValueError('duplicate_pdf_identifier')
    return cards, excluded


def parse_supplement(detail):
    """Accept explicit S/N cells, never infer a missing printed number."""
    cards = []
    for rows in detail['tables']:
        if not rows:
            continue
        headers = [h.casefold() for h in rows[0]]
        def col(pattern):
            return next((i for i, h in enumerate(headers) if re.fullmatch(pattern, h)), None)
        number = col(r'número|numero|nº|number|no\.?')
        name = col(r'nombre|name|jugador|player|descripción|descripcion')
        section = col(r'serie|sección|seccion|section')
        team = col(r'equipo|team')
        if number is None or name is None:
            continue
        for row in rows[1:]:
            if len(row) != len(headers) or not row[number] or not row[name]:
                raise ValueError('supplement_row_incomplete')
            unnumbered = row[number].strip().casefold() in {'s/n', 'sin número', 'sin numero', 'unnumbered'}
            series = row[section] if section is not None else ''
            if unnumbered and not series:
                raise ValueError('unnumbered_series_missing')
            original = None if unnumbered else row[number]
            key = series.upper() + ':' + row[name] if unnumbered else identifier(original)
            cards.append({'n': original, 'original_identifier': original,
                          'key': key, 'player': row[name], 'section': series,
                          'team': row[team] if team is not None else ''})
    if not cards:
        raise ValueError('supplement_checklist_missing')
    if len({c['key'] for c in cards}) != len(cards):
        raise ValueError('duplicate_supplement_identifier')
    return cards


def verify_official(target, client, config):
    from scripts.enrich_collections import permission
    evidence, errors, cards = [], [], []
    def fetch(url):
        final, content_type, raw = client.fetch(url)
        evidence.append({'url': final, 'sha256': hashlib.sha256(raw).hexdigest(),
                         'bytes': len(raw), 'content_type': content_type})
        return raw
    shop_html = fetch(target['shop_url'])
    source_page = BeautifulSoup(shop_html, 'html.parser')
    discovered = []
    for link in source_page.find_all('a', href=True):
        url = urljoin(target['shop_url'], link['href'])
        if (urlsplit(url).hostname == urlsplit(target['shop_url']).hostname
                and urlsplit(url).path.lower().endswith('.pdf')
                and all(token.casefold() in url.casefold() for token in target.get('discovery_tokens', ['MGK', '2025']))):
            if url not in discovered:
                discovered.append(url)
    # Retain the explicit source as fallback; discovered sources must pass the same checks.
    checklist_url = target['checklist_url']
    candidates = sorted(discovered, reverse=True)
    cards, excluded = [], 0
    for url in candidates[:3] + ([checklist_url] if checklist_url not in candidates[:3] else []):
        try:
            parsed, excluded_count = pdf_rows(fetch(url))
            if len(parsed) > len(cards):
                cards, excluded, checklist_url = parsed, excluded_count, url
        except Exception as exc:
            errors.append({'code': getattr(exc, 'code', type(exc).__name__), 'url': url, 'detail': str(exc)})
    if not cards:
        raise ValueError('no_readable_official_checklist')
    shop = shop_rows(shop_html)
    # Optional sources may fail independently; never suppress usable official evidence.
    for source in target.get('supplement_sources', []):
        try:
            raw = fetch(source['url'])
            if len(raw) < 10000 and b'document.location.href' in raw and (b'noscript' in raw or b'cookie' in raw.lower()):
                from scripts.enrich_collections import Blocked
                raise Blocked('javascript_cookie_challenge', source['url'], 'HTTP 200 contiene JavaScript/cookies, no el contenido de Jugón')
            if not permission(source['url'], config):
                errors.append({'code': 'supplement_reuse_not_authorized', 'url': source['url']})
                continue
            from scripts.enrich_collections import parse_detail
            extra = parse_supplement(parse_detail(raw, source['url']))
            if not extra:
                errors.append({'code': 'supplement_checklist_missing', 'url': source['url']})
                continue
            for card in extra:
                key = card['key']
                if key in {c['key'] for c in cards}:
                    raise ValueError('duplicate_supplement_identifier:' + key)
                cards.append({**card, 'source_url': source['url']})
        except Exception as exc:
            errors.append({'code': getattr(exc, 'code', type(exc).__name__),
                           'url': source['url'], 'detail': str(exc)})
    by_key = {card['key']: card for card in cards}
    for key, row in shop.items():
        if key not in by_key:
            errors.append({'code': 'official_sources_disagree', 'identifier': key})
        else:
            def canonical(value):
                ascii_text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().casefold()
                return re.sub(r'[^a-z0-9]', '', ascii_text)
            if canonical(by_key[key]['player']) not in canonical(row.get('description', '')):
                errors.append({'code': 'official_card_name_disagrees', 'identifier': key})
            by_key[key]['shop_identifier'] = row['identifier']
    contrast = None
    if target.get('contrast_url'):
        try:
            contrast_raw = fetch(target['contrast_url'])
            from scripts.enrich_collections import parse_detail, parse_cards
            detail = parse_detail(contrast_raw, target['contrast_url'])
            if 'megacracks' not in detail['title'].casefold() or '2025' not in detail['title']:
                raise ValueError('contrast_collection_identity_mismatch')
            text = ' '.join(' '.join(row) for table in detail['tables'] for row in table)
            contrast = {'url': target['contrast_url'], 'title': detail['title'], 'status': 'metadata_readable',
                'editions_mentioned': [n for n in (1, 2, 3) if re.search(str(n) + r'[ªa]?\s*Edici[oó]n', text, re.I)],
                'jugon_issues_mentioned': [n for n in (222, 223, 224) if re.search(r'Jug[oó]n[^0-9]{0,20}' + str(n), text, re.I)],
                'nine_limited_editions_mentioned': bool(re.search(r'(?:nueve|9)[^.!]{0,90}EDICI[OÓ]N', text, re.I))}
            try:
                compared = parse_cards(detail)
                primary_ids = {c['key'] for c in cards if c['original_identifier'] is not None}
                other_ids = {identifier(c['n']) for c in compared}
                contrast.update(status='identifiers_compared', source_card_count=len(compared),
                    matching_identifiers=len(primary_ids & other_ids),
                    identifiers_only_in_contrast=len(other_ids - primary_ids))
            except ValueError as exc:
                contrast['identifier_blocker'] = str(exc)
            # Contrast is read-only: never import editorial SOB/EDL numbering or copyrighted covers.
        except Exception as exc:
            contrast = {'url': target['contrast_url'], 'status': 'blocked',
                'blocker': {'code': getattr(exc, 'code', type(exc).__name__), 'detail': str(exc)}}
    counts = Counter(card['section'] for card in cards)
    required = target['required_card_count']
    if len(cards) != required:
        errors.append({'code': 'incomplete_collection', 'verified': len(cards),
                       'required': required, 'missing': required - len(cards),
                       'detail': 'Faltan promocionales: no publicar una edición como colección completa'})
    if target.get('numeric_range'):
        actual = {int(card['n']) for card in cards if card['n'] and card['n'].isdigit()}
        start, stop = target['numeric_range']
        if actual != set(range(start, stop + 1)):
            errors.append({'code': 'numbered_range_incomplete'})
    grant = permission(checklist_url, config)
    if not grant:
        errors.append({'code': 'reuse_not_authorized', 'url': checklist_url,
                       'detail': 'Fuente oficial accesible; no consta licencia o permiso de reutilización'})
    # Discover product images from the actual source, never synthesize a URL.
    soup = source_page
    images = []
    for image in soup.find_all('img'):
        url = urljoin(target['shop_url'], image.get('src', ''))
        if target.get('product_image_marker', '') and target['product_image_marker'] in url:
            if urlsplit(url).hostname == urlsplit(target['shop_url']).hostname and url not in images:
                images.append(url)
    for url in images[:1]:
        from PIL import Image
        data = fetch(url)
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        if not permission(url, config):
            errors.append({'code': 'cover_reuse_not_authorized', 'url': url,
                           'detail': 'Imagen oficial verificada; sin permiso para copiarla'})
    return {'id': target['collection_id'], 'verified_card_count': len(cards),
            'official_shop_card_count': len(shop), 'required_card_count': required, 'excluded_autographs': excluded,
            'sections': dict(counts), 'source_evidence': evidence,
            'discovered_checklist_urls': discovered, 'contrast': contrast,
            'official_product_images': images, 'complete': not errors,
            'blockers': errors}, cards


def publish_existing(catalog, target, cards, result):
    """Merge only a complete, permitted checklist. Never transfer states between players."""
    if not result['complete'] or result['blockers']:
        return False
    if target.get('required_card_count') is not None and len(cards) != target['required_card_count']:
        raise ValueError('incomplete_collection_cannot_publish')
    collection = next((c for c in catalog['collections'] if c['id'] == target['collection_id']), None)
    if collection is None:
        raise ValueError('target_collection_not_found')
    def semantic(card):
        value = card.get('section', '') + ':' + card.get('player', '')
        value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().casefold()
        return re.sub(r'[^a-z0-9:]', '', value)
    existing = {}
    unnumbered = {semantic(card): card['key'] for card in cards if card['original_identifier'] is None}
    archive = list(collection.get('legacy_unverified_cards', []))
    for old in collection['cards']:
        printed = identifier(old.get('original_identifier', old.get('n')))
        semantic_key = unnumbered.get(semantic(old))
        if semantic_key is not None:
            key = semantic_key
        elif printed in {c['key'] for c in cards}:
            key = printed
        elif re.fullmatch(r'SO[BG]\d+', str(old.get('n', ''))) and old.get('player'):
            # Retain the original record/ID; do not map its personal state to another player.
            if not any(c['id'] == old['id'] for c in archive):
                archive.append(dict(old))
            continue
        else:
            raise ValueError('existing_identifiers_require_migration:' + printed)
        if key in existing:
            raise ValueError('ambiguous_existing_card_identity:' + key)
        existing[key] = old
    merged = []
    for card in cards:
        old = existing.get(card['key'])
        item = dict(old or {})
        if not old:
            token = hashlib.sha256(card['key'].encode()).hexdigest()[:16]
            item['id'] = target['collection_id'] + '-' + token
            item['n'] = card['n']
        item.update({k: card[k] for k in ('player', 'team', 'section', 'original_identifier')})
        merged.append(item)
    collection.update(cards=merged, card_count=len(merged), verification=result)
    if archive:
        collection['legacy_unverified_cards'] = archive
    return True
