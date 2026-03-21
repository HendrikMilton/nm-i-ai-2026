#!/usr/bin/env python3
"""Strip openapi.json to only keep paths and schemas we actually use."""
import json, re

KEEP_PREFIXES = [
    '/employee', '/department', '/division', '/municipality',
    '/customer', '/supplier', '/contact',
    '/product', '/order', '/invoice',
    '/project', '/timesheet', '/activity',
    '/salary', '/travelExpense', '/ledger',
    '/token', '/currency', '/country',
]

with open('openapi.json') as f:
    oa = json.load(f)

# 1. Filter paths
kept_paths = {}
for path, methods in oa.get('paths', {}).items():
    if any(path.startswith(p) for p in KEEP_PREFIXES):
        kept_paths[path] = methods

# 2. Find all schema refs from kept paths (recursive)
schemas = oa.get('components', {}).get('schemas', {})

def find_all_refs(obj, found=None):
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == '$ref' and isinstance(v, str) and v.startswith('#/components/schemas/'):
                name = v.split('/')[-1]
                if name not in found:
                    found.add(name)
                    if name in schemas:
                        find_all_refs(schemas[name], found)
            else:
                find_all_refs(v, found)
    elif isinstance(obj, list):
        for item in obj:
            find_all_refs(item, found)
    return found

needed = find_all_refs(kept_paths)

# 3. Build stripped output
result = {
    'openapi': oa.get('openapi'),
    'info': {'title': oa.get('info', {}).get('title', ''), 'version': oa.get('info', {}).get('version', '')},
    'paths': kept_paths,
    'components': {
        'schemas': {name: schemas[name] for name in sorted(needed) if name in schemas}
    }
}

out = json.dumps(result, ensure_ascii=False)
with open('api-stripped.json', 'w') as f:
    f.write(out)

print(f'Paths: {len(oa["paths"])} -> {len(kept_paths)}')
print(f'Schemas: {len(schemas)} -> {len(needed)}')
print(f'Size: {len(json.dumps(oa)):,} -> {len(out):,} chars ({len(out)*100//len(json.dumps(oa))}%)')
print(f'Estimated tokens: ~{len(out)//4:,}')
