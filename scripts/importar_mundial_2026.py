"""Extrae un listado copiado sin modificar el catálogo ni estados personales."""
import argparse
import json
import re
from pathlib import Path

PREFIX = re.compile(r"^(?:\d+)?[·•]\s*(.+)$")
NUMBER = re.compile(r"^(\d+|FTS\d+|U\d+)\s*\.\s*-\s*(.+)$", re.I)
SUMMARY = re.compile(r"^\d+\s+(?:faltas?|cartas?|repetidas?)\b", re.I)


def parse(text):
    cards, issues, seen = [], [], set()
    section = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip('\ufeff').strip()
        if not line or SUMMARY.match(line) or line == 'forward_to_inbox':
            continue
        prefixed = PREFIX.match(line)
        payload = prefixed.group(1) if prefixed else line
        numbered = NUMBER.match(payload)
        if not prefixed and not numbered:
            section = line
            continue
        if section is None:
            issues.append({'linea': line_number, 'motivo': 'Carta sin sección'})
            continue
        number, name = numbered.groups() if numbered else (None, payload)
        # Los contadores de la fuente no son parte del nombre ni posesiones.
        name = re.sub(r'\s+\d+$', '', name).strip()
        number = number.upper() if number else None
        key = (section, number, name)
        if key in seen:
            issues.append({'linea': line_number, 'motivo': 'Fila duplicada', 'numero': number})
            continue
        seen.add(key)
        cards.append({'numero': number, 'nombre': name, 'seccion': section})
    numbers = {int(c['numero']) for c in cards if c['numero'] and c['numero'].isdigit()}
    groups = {}
    for card in cards:
        if card['numero'] is not None:
            groups.setdefault((card['seccion'], card['numero']), set()).add(card['nombre'])
    report = {
        'cartas': len(cards), 'secciones': len({c['seccion'] for c in cards}),
        'numeros_ausentes_1_648': sorted(set(range(1, 649)) - numbers),
        'sin_numero_impreso': sum(c['numero'] is None for c in cards),
        'numeros_con_nombres_distintos': [
            {'seccion': s, 'numero': n, 'nombres': sorted(names)}
            for (s, n), names in groups.items() if len(names) > 1
        ],
        'incidencias': issues, 'estado': 'pendiente_de_revision',
    }
    return cards, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origen', type=Path, default=Path('importaciones/mundial_2026.txt'))
    parser.add_argument('--destino', type=Path, default=Path('importaciones/mundial_2026_limpio.json'))
    args = parser.parse_args()
    cards, report = parse(args.origen.read_text(encoding='utf-8-sig'))
    if not cards:
        parser.error('No se han detectado cartas; no se sobrescribe la salida.')
    if args.destino.resolve() == args.origen.resolve() or args.destino.name == 'catalogo.json':
        parser.error('La salida debe ser un archivo de importación independiente.')
    args.destino.parent.mkdir(parents=True, exist_ok=True)
    args.destino.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.destino.with_suffix('.informe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
