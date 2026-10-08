"""Stage only public site assets; verification reports and source PDFs stay private."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(root=ROOT, destination=None):
    destination = destination or root / 'site'
    catalog = json.loads((root / 'catalogo.json').read_text(encoding='utf-8'))
    collection_ids, global_ids = set(), set()
    for collection in catalog['collections']:
        if not collection.get('id') or collection['id'] in collection_ids:
            raise ValueError('duplicate_collection_id')
        collection_ids.add(collection['id'])
        ids = [card.get('id') for card in collection['cards']]
        if not all(ids) or len(ids) != len(set(ids)) or global_ids.intersection(ids):
            raise ValueError('duplicate_or_missing_card_id')
        global_ids.update(ids)
        verification = collection.get('verification', {})
        if verification.get('complete'):
            if verification.get('blockers') or collection['card_count'] != len(ids):
                raise ValueError('invalid_complete_collection')
            expected = verification.get('required_card_count')
            if expected is not None and expected != len(ids):
                raise ValueError('incomplete_collection_cannot_deploy')
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'catalogo.json', 'servidor.config.json', 'manifest.json'):
        shutil.copy2(root / name, destination / name)
    covers = destination / 'portadas'
    covers.mkdir(exist_ok=True)
    for source in (root / 'portadas').iterdir():
        if source.is_file() and source.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'}:
            shutil.copy2(source, covers / source.name)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'site')
    args = parser.parse_args()
    print(build(destination=args.output))
