# DesignStructure.md

## Architecture: Universal Multi-Product Pipeline

### Entry Points
- `run.py` — universal runner, reads config from `jobs.json`

### Configuration File: jobs.json
```json
{
  "jobs": [
    {
      "name": "Brew",
      "db":    "SysConfig_Lib_Brew.db",
      "excel": "testLBB.xlsx",
      "families": {
        "BREW 350": 7, "BREW 450": 8, "BREW 600": 9,
        "BREW 750H": 10, "BREW 600e": 11, "BREW 750e": 12, "BREW 750L": 13
      },
      "out_db":   "SysConfig_Lib_Brew_updated.db",
      "out_xlsx": "Brew_Comparison.xlsx"
    }
  ]
}
```
- `families` dict: **key** = exact Excel column header, **value** = MachineConfig array index
- Jobs with empty `"families": {}` are skipped (printed as PENDING)

### Processing Pipeline (per job in run.py)

```
jobs.json ──► run_job(job)
                 │
                 ├─[1] Read DB text
                 │
                 ├─[2] build_tag_map(db_text)
                 │       ┌─ Step A: scan BEGIN section for any MachineConfig[N]."unit"."em".
                 │       │          → em → unit mapping (no manual input)
                 │       └─ Step B: scan TYPE "EM-xxx" blocks for STAT-typed fields
                 │                  → {field: (unit, em, field, is_vlv)}
                 │
                 ├─[3] parse_excel(path, families_cfg, tag_map)
                 │       → {family_name: {tag_label: {enable, exist, vlv_w_fb, ...}}}
                 │
                 ├─[4] parse_type_defaults(db_text, tag_map)
                 │       → {path_key: {default_enable, default_exist, default_vlv_w_fb}}
                 │
                 ├─[5] parse_mc_overrides(db_text, mc_idx)  [per family]
                 │       → {mc_idx: {path_key: {enable, exist, vlv_w_fb}}}
                 │
                 ├─[6] build_comparison(...)
                 │       → list of comparison dicts (one row per instrument)
                 │
                 ├─[7] write_comparison_xlsx(rows, out_xlsx, families_cfg, job_name)
                 │       → <name>_Comparison.xlsx
                 │
                 ├─[8] generate_updated_db(...)
                 │       → SysConfig_Lib_<name>_updated.db
                 │
                 └─[9] verify_updated_db(...)
                         → all ENABLE/EXIST values confirmed correct
```

### Tag Label → Unit + EM Mapping Flow

```
STAT SYSTEM.udt ──► build_em_unit_from_udt() ──► em_unit dict
                                                      │
                                                      ▼
DB TYPE blocks   ──► build_tag_map(db_text, em_unit) ──► tag_map
                                                              │
                         {"AV201-1": ("Unit Process", "EM - 201", "AV201-1", True ),
                          "EMS":     ("Unit Sep",     "EM - 100", "EMS",     False),
                          "PIT22X-1":("Unit Process", "EM - 22X", "PIT22X-1",False),
                          ...}
                                                              │
testLBB.xlsx ──► parse_excel() ──► per-family resolved_tag   │
                                        │                     │
                                        ▼                     ▼
                               build_comparison() ──► tag_map[resolved_tag]
                                                              │
                                        ┌─────────────────────┤
                                        ▼                     ▼
                                  "Unit Process"        "EM - 201"
                                  (Unit column)       (EM Module column)
```

The `tag_map` key is always the **DB field name** (from `TYPE "EM-xxx"` blocks).
`resolved_tag` = DB field name to use per family — see Cell Comment Rules below.

### Cell Comment Rules — Two Cases

**Case A: Excel label = DB field name** (most tags)
The DB `TYPE` block field name uses the same X-placeholder as the Excel label.
The cell comment is the internal TAG string (hardware label), not the DB key.

```
Excel Col B   DB field (tag_map key)   Cell comment = internal TAG value
───────────   ────────────────────────  ─────────────────────────────────
PIT22X-1   →  "PIT22X-1" in EM-22X     comment: PIT220-1   (lookup uses PIT22X-1)
AV37X-1    →  "AV37X-1"  in EM-375     comment: AV375-1
YT75X      →  YT75X       in EM-750     comment: YT750
AVDCH      →  AVDCH       in EM-506     comment: 506c / 506b
LS42X(b)   →  "LS42X(b)" in EM-420     comment: LS422b / LS423
TT41X-1    →  "TT41X-1"  in EM-400     comment: TT410-1 / TT412-1
```
→ `resolved_tag = tag_label` (comment ignored for DB lookup)

**Case B: Excel label ≠ DB field name — comment varies per family column**
The Excel Col B is a generic display name. Each family column cell comment
gives the actual DB field name for that specific family.

```
Excel Col B    BREW 350         BREW 450         BREW 600  ...
────────────   ──────────────   ──────────────   ──────────
ST74X          val=x            val=x            val=x
               comment=ST741    comment=ST740    comment=ST741

TT730          val=x (col J)    (empty)          (empty)
               comment=TT730a

TT731b/TT733   (empty)          val=x            (empty)
                                comment=TT733
```
→ `resolved_tag = cell_comment` per family (varies per column)

`parse_excel()` stores `resolved_tag` per instrument per family.
`build_comparison()`, `generate_updated_db()`, and `verify_updated_db()` all
use `inst.get("resolved_tag", tag_label)` for every tag_map lookup.

### Key Functions in run.py

#### `build_em_unit_from_udt(udt_text)` — UDT-based EM→Unit mapping
```python
# Pass 1: STAT SYSTEM block → {stat_type_name: unit_name}
# e.g. {"STAT Sep": "Unit Sep", "STAT Options": "Options", ...}

# Pass 2: each STAT_xxx block → {em_name: unit_name}
# e.g. {"EM - 100": "Unit Sep", "EM - 208": "Options", ...}
```
Loaded once at script start. Replaces the old BEGIN-section scan — every EM
is always mapped correctly regardless of what override lines exist in the DB.

#### `build_tag_map(db_text, em_unit)` — instrument field discovery
```python
# Scan TYPE "EM-xxx" blocks for STAT-typed instrument fields
for each TYPE block starting with "EM":
    unit = em_unit.get(em, "Unknown")   # from UDT, not from DB BEGIN
    for each field with ": "STAT VLV/DI/DO/AI/AO/MTR/VFD" :=":
        tag_map[field] = (unit, em, field, is_vlv)
```

#### `parse_excel(path, families_cfg, tag_map)`
- Auto-detects family columns, Option column, and **Type column** (`cell.value.lower() == "type"`)
- Per value cell: stores `resolved_tag = comment or tag_label` in instrument dict
- Aggregates AV valve rows (FB OPN / FB CLS / ACT) separately from non-valve rows
- option_tags = {tag for tag, info in tag_map.items() if info[0] == "Options"}
  → these tags get ENABLE=False, EXIST=False unconditionally (VLV_W_FB/NO/FB follows normal logic)
- Type column → `no_val`: NC→False, NO→True, other/empty→None (no override)
- FB OPN / FB CLS x or o → `fb_opn_en=True` / `fb_cls_en=True`, VLV_W_FB=True
- Both FB empty → VLV_W_FB=False, FB_OPN_EN=False, FB_CLS_EN=False

#### `parse_type_defaults(db_text, tag_map)`
- Derives em→unit from tag_map (not hardcoded)
- Walks `TYPE ... END_TYPE` blocks; for each STAT field finds CW tuple
- Extracts: bit 3=ENABLE, bit 6=FB_CLS_EN (VLV), bit 7=FB_OPN_EN (VLV),
            bit 12=NO, bit 13=EXIST, bit 15=VLV_W_FB (VLV)
- `()` element in tuple = False (Siemens convention)

#### `parse_mc_overrides(db_text, mc_idx)`
- Regex: `MachineConfig[N]."unit"."em"."field".CW.(ENABLE|EXIST|VLV_W_FB) := (True|False)`
- Both quoted and unquoted field names handled

#### `generate_updated_db(...)`
- Uses `inst.get("resolved_tag", tag_label)` for tag_map lookup (handles Case B)
- Pass 1: strip all existing CW lines for the target MC indices
- Pass 2: reinsert minimal-patch CW lines only where expected ≠ type default
- Insert comment header `// === CW auto-patched for MachineConfig[N] ===` per block
- Handles special field names with parentheses/hyphens by quoting them (e.g. `"LS42X(b)"`)

#### `verify_updated_db(...)`
- Uses `inst.get("resolved_tag", tag_label)` for tag_map lookup (handles Case B)
- Re-parses the updated DB text and checks ENABLE/EXIST per tag per family
- Reports any remaining mismatches to stdout

### path_key Convention
```python
def path_key(unit, em, field):
    return f"{unit}|{em}|{field}"
```
Used as the dict key throughout the pipeline to link Excel instruments to DB paths.

### CW Bit Layout
| Bit | Property   | CW Type  | Notes                                |
|-----|------------|----------|--------------------------------------|
| 3   | ENABLE     | Both     | All STAT types                       |
| 6   | FB_CLS_EN  | CW_VLV   | Enable Close Feedback (STAT VLV)     |
| 7   | FB_OPN_EN  | CW_VLV   | Enable Open Feedback (STAT VLV)      |
| 12  | NO         | Both     | 0=NC (False), 1=NO (True)            |
| 13  | EXIST      | Both     | All STAT types                       |
| 15  | VLV_W_FB   | CW_VLV   | Valve Without Position Feedback      |

DB comment: `NO : Bool // 0=NC, 1=NO`
Excel Type column → NO bit: NC → False, NO → True, 4..20MA/empty → no override

### Multi-Product Portability
All 5 DBs (Brew, Clara, CR, KR, PP) share the same 30 TYPE "EM-XXX" block definitions.
`build_tag_map()` works identically for all — no product-specific code.
The only product-specific configuration is `families` in `jobs.json`.

### STAT Types Recognized
```python
STAT_TYPES = {"STAT VLV", "STAT DI", "STAT DO", "STAT AI", "STAT AO", "STAT MTR", "STAT VFD"}
```

### Comparison Excel Format
- Row 1: Title banner (merged)
- Row 2: Family group headers (merged per family)
- Row 3: Sub-column headers (frozen after col 4)
- Row 4+: Data — one row per instrument

Per-family sub-columns (16 per family):
```
Excel Val | Type(NC/NO) | Exp EN | Exp EX | Exp VF | Exp NO | Exp FBOPN_EN | Exp FBCLS_EN |
                          DB EN  | DB EX  | DB VF  | DB NO  | DB FBOPN_EN  | DB FBCLS_EN  | Match | Action
```

Color coding: green = OK/True, red = MISMATCH, yellow = NOT_FOUND/warning

### Usage
```
python run.py               # run all jobs in jobs.json with families configured
python run.py Brew          # run one job by name
python run.py --list        # list jobs and status
```
