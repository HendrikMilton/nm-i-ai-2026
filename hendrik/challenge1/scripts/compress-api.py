"""
Compress api-summary.json with short keys, drop descriptions.
Keys: m=method, p=path, s=summary, f=fields, t=type, r=required
"""
import json

with open('api-summary.json') as f:
    data = json.load(f)

compressed = {}
for tag, endpoints in data.items():
    items = []
    for ep in endpoints:
        item = {
            'm': ep['method'],
            'p': ep['path'],
        }
        if ep.get('summary'):
            item['s'] = ep['summary']
        if ep.get('fields'):
            fields = {}
            for fname, fdef in ep['fields'].items():
                f = {'t': fdef['type']}
                if fdef.get('required'):
                    f['r'] = 1
                fields[fname] = f
            item['f'] = fields
        items.append(item)
    compressed[tag] = items

out = json.dumps(compressed, ensure_ascii=False, separators=(',', ':'))
with open('api-compact.json', 'w') as f:
    f.write(out)

print(f'Original:      {len(open("api-summary.json").read()):,} bytes')
print(f'No desc:       {len(out):,} bytes')
print(f'Approx tokens: ~{len(out)//4:,}')
