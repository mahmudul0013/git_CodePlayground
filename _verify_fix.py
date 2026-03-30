import re

with open("SysConfig_Lib_Brew.db", encoding="utf-8", errors="replace") as f:
    db = f.read()

# Reproduce build_tag_map logic
STAT_TYPES = {"STAT VLV", "STAT DI", "STAT DO", "STAT AI", "STAT AO", "STAT MTR", "STAT VFD"}

em_unit = {}
for m in re.finditer(
    r'MachineConfig\[\d+\]\.(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_]*))\."([^"]+)"\.',
    db
):
    unit = m.group(1) or m.group(2)
    em   = m.group(3)
    em_unit[em] = unit

tag_map = {}
type_pat  = re.compile(r'TYPE\s+"([^"]+)".*?END_TYPE', re.DOTALL)
field_pat = re.compile(
    r'(?:"([^"]+)"|([A-Za-z0-9_\-\+\./]+))'
    r'(?:\s*\{[^}]*\})?'
    r'\s*:\s*"(STAT [A-Z]+)"\s*:=',
    re.DOTALL
)
for type_m in type_pat.finditer(db):
    em = type_m.group(1)
    if not em.startswith("EM"):
        continue
    unit = em_unit.get(em, "Unknown")
    for fm in field_pat.finditer(type_m.group(0)):
        field     = (fm.group(1) or fm.group(2)).strip()
        stat_type = fm.group(3)
        if stat_type not in STAT_TYPES:
            continue
        if field not in tag_map:
            tag_map[field] = (unit, em, field, stat_type == "STAT VLV")

option_tags = {tag for tag, info in tag_map.items() if info[0] == "Options"}

print(f"Total instruments: {len(tag_map)}")
print(f"Option tags ({len(option_tags)}):")
for t in sorted(option_tags):
    print(f"  {t:25s} -> {tag_map[t]}")

print()
checks = ["AV208-1", "FCV208-1", "FIT208-1", "AV210-1", "FCV210-1", "P463-1", "P201-1"]
print("Instrument check:")
for tag in checks:
    info = tag_map.get(tag)
    if info:
        is_opt = tag in option_tags
        print(f"  {tag:20s}  unit={info[0]:20s}  option={is_opt}")
    else:
        print(f"  {tag:20s}  NOT IN TAG_MAP")
