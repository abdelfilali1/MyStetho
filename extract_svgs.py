import urllib.request, re, os, sys

out_dir = r'c:\Users\abdel\Documents\PlatformIO\Projects\Learn CC\medfollow\static\ngap'
os.makedirs(out_dir, exist_ok=True)

print('Fetching bundle...')
req = urllib.request.Request(
    'https://www.ngap-maroc.com/assets/index-B880O5Z6.js',
    headers={'User-Agent': 'Mozilla/5.0'}
)
with urllib.request.urlopen(req, timeout=90) as resp:
    content = resp.read().decode('utf-8', errors='replace')
print(f'Bundle size: {len(content)} chars')

# Find all positions where a template literal contains 297mm (A4 SVG marker)
needle = '297mm'
positions = []
pos = 0
while True:
    idx = content.find(needle, pos)
    if idx == -1:
        break
    positions.append(idx)
    pos = idx + 1

print(f'Found {len(positions)} occurrences of 297mm')

# For each occurrence, walk backwards to find the opening backtick + variable name
svgs_found = []
for svg_pos in positions:
    # Search backwards up to 500 chars for a backtick
    search_back = max(0, svg_pos - 2000)
    chunk = content[search_back:svg_pos]
    # Find the last backtick in this chunk
    bt_idx = chunk.rfind('`')
    if bt_idx == -1:
        continue
    abs_bt = search_back + bt_idx
    # Get variable name (up to 4 chars before =`)
    pre = content[max(0, abs_bt-10):abs_bt]
    var_match = re.search(r'(\w+)=$', pre)
    if not var_match:
        continue
    var_name = var_match.group(1)
    if any(v == var_name for v, _ in svgs_found):
        continue

    # Now extract the full template literal from abs_bt+1 to closing backtick
    start = abs_bt + 1
    p = start
    while p < len(content):
        ch = content[p]
        if ch == '\\':
            p += 2
            continue
        if ch == '`':
            break
        p += 1
    raw = content[start:p]
    print(f'  Found: {var_name} at {abs_bt}, length={len(raw)}')
    svgs_found.append((var_name, raw))

# Map to output files — we expect 4 SVGs
# Identify by size and content hints
print('\nAll SVGs found:')
for i, (name, svg) in enumerate(svgs_found):
    has_cnops = 'CNOPS' in svg or 'cnops' in svg.lower()
    has_cnss = 'CNSS' in svg or 'cnss' in svg.lower()
    has_verso = 'showArray' in svg or 'each soins' in svg
    print(f'  [{i}] var={name} len={len(svg)} cnops={has_cnops} cnss={has_cnss} verso={has_verso}')

# Save all
for i, (name, svg) in enumerate(svgs_found):
    has_verso = 'showArray' in svg or 'each soins' in svg
    has_cnss = 'CNSS' in svg

    if has_verso:
        suffix = 'verso'
    else:
        suffix = 'recto'

    if has_cnss:
        org = 'cnss'
    else:
        org = 'cnops'

    fname = f'{org}_{suffix}.svg'
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print(f'Saved: {fname} ({os.path.getsize(path)} bytes)')

print('Done.')
