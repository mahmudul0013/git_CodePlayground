# DesignStructure.md

## Architecture: Universal Multi-Product Pipeline

### Entry Points
- `run.py` — universal runner, reads config from `jobs.json` (**recommended**)
- `main.py` — legacy Brew-only script with hardcoded TAG_MAP (kept for reference)

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

### Key Functions in run.py

#### `build_tag_map(db_text)` — Auto-Discovery (no manual input)
```python
# Step 1: derive em → unit from any path line in BEGIN section
em_unit = {}
for m in re.finditer(r'MachineConfig\[\d+\]\."([^"]+)"\."([^"]+)"\.', db_text):
    em_unit[m.group(2)] = m.group(1)   # em_name → unit_name

# Step 2: scan TYPE "EM-xxx" blocks for STAT-typed instrument fields
for each TYPE block starting with "EM":
    for each field with ": "STAT VLV/DI/DO/AI/AO/MTR/VFD" :=":
        tag_map[field] = (unit, em, field, is_vlv)
```

#### `parse_excel(path, families_cfg, tag_map)`
- Auto-detects family columns by matching header values against `families_cfg` keys
- Auto-detects Option column (`cell.value.lower() == "option"`)
- Reads openpyxl cell comments for resolved tag name aliases
- Aggregates AV valve rows (FB OPN / FB CLS / ACT) separately from non-valve rows
- option_tags = {tag for tag, info in tag_map.items() if info[0] == "Options"}
  → these tags get ENABLE=EXIST=VLV_W_FB=False unconditionally

#### `parse_type_defaults(db_text, tag_map)`
- Derives em→unit from tag_map (not hardcoded)
- Walks `TYPE ... END_TYPE` blocks; for each STAT field finds CW tuple
- CW bit 3=ENABLE, bit 13=EXIST, bit 15=VLV_W_FB (VLV only)
- `()` element in tuple = False (Siemens convention)

#### `parse_mc_overrides(db_text, mc_idx)`
- Regex: `MachineConfig[N]."unit"."em"."field".CW.(ENABLE|EXIST|VLV_W_FB) := (True|False)`
- Both quoted and unquoted field names handled

#### `generate_updated_db(...)`
- Pass 1: strip all existing CW lines for the target MC indices
- Pass 2: reinsert minimal-patch CW lines only where expected ≠ type default
- Insert comment header `// === CW auto-patched for MachineConfig[N] ===` per block
- Handles special field names with parentheses/hyphens by quoting them (e.g. `"LS42X(b)"`)

#### `verify_updated_db(...)`
- Re-parses the updated DB text and checks ENABLE/EXIST per tag per family
- Reports any remaining mismatches to stdout

### path_key Convention
```python
def path_key(unit, em, field):
    return f"{unit}|{em}|{field}"
```
Used as the dict key throughout the pipeline to link Excel instruments to DB paths.

### CW Bit Layout
| Bit | Property  | Notes             |
|-----|-----------|-------------------|
| 3   | ENABLE    | All STAT types    |
| 13  | EXIST     | All STAT types    |
| 15  | VLV_W_FB  | STAT VLV only     |

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

Per-family sub-columns (9 per family):
`Excel Val | Exp EN | Exp EX | Exp VF | DB EN | DB EX | DB VF | Match | Action`

Color coding: green = OK/True, red = MISMATCH, yellow = NOT_FOUND/warning

### Usage
```
python run.py               # run all jobs in jobs.json with families configured
python run.py Brew          # run one job by name
python run.py --list        # list jobs and status
```
