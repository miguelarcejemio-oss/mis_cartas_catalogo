"""Apply reviewed descriptive titles without changing any card/parallel identity."""
import copy
import json
from pathlib import Path

COLLECTION = 'panini-dragon-ball-daima-tcg'


def integrate(catalog, snapshot):
    result = copy.deepcopy(catalog)
    if snapshot['collection_id'] != COLLECTION:
        raise ValueError('wrong_daima_edition')
    rows = snapshot['cards']
    if len(rows) != 207 or {r['n'] for r in rows} != set(range(1, 208)) or len({r['id'] for r in rows}) != 207:
        raise ValueError('incomplete_or_duplicate_daima_snapshot')
    target = next(c for c in result['collections'] if c['id'] == COLLECTION)
    current = {c['id']: c for c in target['cards']}
    if len(current) != len(target['cards']):
        raise ValueError('duplicate_existing_daima_ids')
    for row in rows:
        card = current.get(row['id'])
        if card is None or str(card['n']) != str(row['n']):
            raise ValueError('daima_identity_changed:' + row['id'])
        if card['player'] not in {row['previous_name'], row['name'], row['source_title']}:
            raise ValueError('daima_title_changed_review_required:' + row['id'])
        card['player'] = row['name']
        card['original_name'] = row['source_title']
    target['card_count'] = len(target['cards'])
    target['checklistVersion'] = max(2, int(target.get('checklistVersion') or 0))
    note = ('216 cartas (207 de la colección y 9 limitadas), con 200 paralelas opcionales. '
            'Personajes y descripciones de escenas identificados por número; '
            'las limitadas y los identificadores anteriores se conservan.')
    target['source'] = note
    target['expected_note'] = note
    target['descriptive_titles'] = {
        'revision': snapshot['revision'], 'checked_at': snapshot['checked_at'],
        'source_url': snapshot['names_source'],
        'edition_source_url': snapshot['edition_source'],
        'scope': 'Títulos descriptivos de las cartas 1–207, no nombres impresos por Panini'}
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / 'catalogo.json'
    original = json.loads(path.read_text(encoding='utf-8'))
    snapshot = json.loads((root / 'importaciones/dragon_ball_daima_nombres.json').read_text(encoding='utf-8'))
    result = integrate(original, snapshot)
    if result != original:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Daima: 207 títulos descriptivos; IDs, limitadas y paralelas conservados.')


if __name__ == '__main__':
    main()
