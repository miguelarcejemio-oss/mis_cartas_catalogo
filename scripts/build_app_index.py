"""Publish the small-index endpoint used by installed Mis Cartas 1.25 APKs.

Keep their bundled catalogue references intact. Updated editions are included
inline, so an older APK never needs a new local shard or an application upgrade.
"""
import copy
import json

WORLD_CUP = 'panini-fifa-wc-2026-adrenalyn'


def app_index(catalog, seed):
    result = copy.deepcopy(seed)
    entries = result['collections']
    if len({c['id'] for c in entries}) != len(entries):
        raise ValueError('duplicate_app_index_entry')
    fresh = next((c for c in catalog['collections'] if c['id'] == WORLD_CUP), None)
    position = next((i for i, c in enumerate(entries) if c['id'] == WORLD_CUP), None)
    if fresh is not None:
        fresh = copy.deepcopy(fresh)
        old = entries[position] if position is not None else None
        if len(fresh.get('cards', [])) < int((old or {}).get('card_count') or 0):
            raise ValueError('world_cup_index_would_shrink')
        ids = [c['id'] for c in fresh['cards']]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError('invalid_world_cup_ids')
        # Inline data must not advertise the obsolete bundled 728-card shard.
        for key in ('public_checklist_file', 'public_checklist_sha256',
                    'bundled_checklist', '_checklistStored'):
            fresh.pop(key, None)
        fresh['card_count'] = len(ids)
        if position is None:
            entries.append(fresh)
        else:
            entries[position] = fresh
    result['updated'] = catalog.get('updated', result.get('updated'))
    result['schema_version'] = seed.get('schema_version', 1)
    return result


def build_app_index(root, destination, catalog):
    path = root / 'importaciones/app_catalog_index_v125.json'
    if not path.exists():
        return  # Small build/test fixtures may not include the APK snapshot.
    seed = json.loads(path.read_text(encoding='utf-8'))
    result = app_index(catalog, seed)
    (destination / 'catalog-index.json').write_text(
        json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n',
        encoding='utf-8')
