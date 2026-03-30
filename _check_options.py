import re

with open('SysConfig_Lib_Brew.db', encoding='utf-8', errors='replace') as f:
    db = f.read()

em_unit = {}
for m in re.finditer(
    r'MachineConfig\[\d+\]\.(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_]*))\"([^"]+)"\.',
    db
):
    unit = m.group(1) or m.group(2)
    em   = m.group(3)
    em_unit[em] = unit

# Also try without inner quote confusion
em_unit2 = {}
pat = re.compile(r'MachineConfig\[\d+\]\.(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_]*))\."([^"]+)"\.')
for m in pat.finditer(db):
    unit = m.group(1) or m.group(2)
    em   = m.group(3)
    em_unit2[em] = unit

print(f'Method1 EMs found: {len(em_unit)}')
print(f'Method2 EMs found: {len(em_unit2)}')
print()
print('All EMs and units (method2):')
for em, unit in sorted(em_unit2.items()):
    print(f'  {em:25s} -> {unit}')
print()
print('AV208-1 unit (EM-208):', em_unit2.get('EM - 208', 'NOT FOUND'))
print('Options EMs:', [em for em, u in em_unit2.items() if u == 'Options'])
