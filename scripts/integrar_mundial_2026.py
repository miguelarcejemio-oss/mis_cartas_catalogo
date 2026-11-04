"""Integra únicamente cartas con número impreso; conserva IDs y datos existentes."""
import copy
import json
import re
from pathlib import Path
from scripts.importar_mundial_2026 import parse

COLLECTION = 'panini-fifa-wc-2026-adrenalyn'
SECTIONS = {'MÉJICO': 'MÉXICO', 'GANA': 'GHANA',
            'REPÚBLICA DE COREA': 'COREA DEL SUR', 'PAISES BAJOS': 'PAÍSES BAJOS'}


def section(value):
    return SECTIONS.get(value, value)


def integrate(catalog, rows):
    result = copy.deepcopy(catalog)
    target = next(c for c in result['collections'] if c['id'] == COLLECTION)
    incoming = {}
    for row in rows:
        if row['numero'] is None:
            continue
        key = str(row['numero'])
        if key in incoming:
            raise ValueError('Número repetido: ' + key)
        incoming[key] = row
    if not set(map(str, range(1, 649))).issubset(incoming):
        raise ValueError('Falta parte de la numeración base')
    existing = {}
    for card in target['cards']:
        key = str(card['n'])
        if key in existing:
            raise ValueError('Número existente ambiguo: ' + key)
        existing[key] = card
        row = incoming.get(key)
        if row is None:
            raise ValueError('Carta existente ausente en fuente: ' + key)
        # Una corrección ortográfica de sección o un contador al final son
        # seguros. Otros cambios de identidad exigen revisar la fuente.
        old_name = card['player']
        if old_name != row['nombre'] and re.sub(r'\s+\d+$', '', old_name) != row['nombre']:
            raise ValueError('Identidad cambiada: ' + key)
        if section(card['section']) != section(row['seccion']):
            raise ValueError('Sección cambiada: ' + key)
    for key, row in incoming.items():
        if key in existing:
            card = existing[key]
        else:
            card = {'id': COLLECTION + '-' + key,
                    'n': int(key) if key.isdigit() else key, 'tag': ''}
            target['cards'].append(card)
        card['player'] = row['nombre']
        card['section'] = section(row['seccion'])
        card['team'] = section(row['seccion'])
    ids = [c['id'] for c in target['cards']]
    if len(set(ids)) != len(ids):
        raise ValueError('Colisión de identificadores')
    target['card_count'] = len(target['cards'])
    target['checklist_status'] = 'partial'
    target['expected_note'] = ('Listado recuperado de CromosRepes: numeración base, FTS y Upgrade. '
        'Variantes sin número pendientes de revisión. Sin autógrafos originales.')
    target['verification'] = {'complete': False,
        'scope': 'Numeración base 1–648, FTS1–80 y U01–48 del listado recuperado',
        'blockers': ['Variantes sin número impreso pendientes de revisar'],
        'source_evidence': 'rescate/2026-11-04/importaciones/mundial_2026.txt'}
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'rescate/2026-11-04/importaciones/mundial_2026.txt'
    rows, report = parse(source.read_text(encoding='utf-8-sig'))
    if report['incidencias'] or report['numeros_con_nombres_distintos']:
        raise ValueError('Fuente con incidencias; revisar antes de integrar')
    path = root / 'catalogo.json'
    original = json.loads(path.read_text(encoding='utf-8'))
    result = integrate(original, rows)
    if result != original:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Mundial integrado; IDs anteriores conservados y variantes sin número pendientes.')


if __name__ == '__main__':
    main()
