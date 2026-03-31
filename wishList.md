# wishList.md

## Goal
Cross-check Siemens TIA Portal DB default values against hardware specification Excel.
Support all product families (Brew, Clara, CR, PP, KR) using a single universal runner.
Produce a separate comparison report and corrected updated `.db` per product — importable directly into TIA Portal.

## Processing Rules

### Excel Tag Reading Rules (per family column)
- `X` or `x`  → ENABLE = True,  EXIST = True
- `o`          → ENABLE = True,  EXIST = False
- empty/SPARE  → ENABLE = False, EXIST = False

### Option Module Rule (based on Function column)
If a tag is found under **`Options."EM - XXX"`** in the DB (unit = `"Options"` in auto-discovered tag map):
(if tag **is** option-type)
- ENABLE = False,  EXIST = False  — unconditionally, regardless of Excel value.


### VLV_W_FB / FB_OPN_EN / FB_CLS_EN Logic (AV valves only, CW_VLV)
- FB OPN = `x` or `o`  →  FB_OPN_EN = True  AND  VLV_W_FB = True
- FB CLS = `x` or `o`  →  FB_CLS_EN = True  AND  VLV_W_FB = True
- FB OPN AND FB CLS = spare or empty  →  VLV_W_FB = False, FB_OPN_EN = False, FB_CLS_EN = False

### NO Tag Logic (Excel `Type` column → CW bit 12)
Applies to both CW_VLV (AV valves) and CW_AN (analog instruments).
DB comment: `NO : Bool // 0=NC, 1=NO`

| Excel Type | CW.NO | Meaning |
|---|---|---|
| `NC` | False | Normally Closed output (0=NC, PLC output direct) |
| `NO` | True  | Normally Open output (1=NO, PLC output inverted) |
| `4..20MA` / empty | no override | Keep type default |

### Valve ENABLE/EXIST Source
- AV valves: ENABLE/EXIST determined by the **ACT** row for that valve
- VLV_W_FB / FB_OPN_EN / FB_CLS_EN determined by FB OPN / FB CLS rows

### Non-Valve ENABLE/EXIST Source
- Direct column value → ENABLE/EXIST

### Tag Resolution via Cell Comments
- If the family column cell has a comment, the comment gives the RESOLVED tag label
  used in the DB (e.g. PCV22X-1 col-D comment = `PCV220-1` → resolved tag is PCV220-1)
- Script automatically reads openpyxl cell comments for all value cells

### Effective DB Value
- Effective = MachineConfig[N] override (from BEGIN section) if present,
  else = type definition default (parsed from TYPE ... STRUCT blocks)
- Default for unset Bool = False (Siemens convention: `()` in tuple = False)

### Minimal Patch Rule
- Only write a CW override line when expected value differs from the type default
- Do NOT duplicate lines that already match the type default
- Preserve all non-CW lines (Address, Type, Max, Tag, etc.) unchanged

### Default Fallback
- If a tag is not found in the DB at all: ENABLE = False, EXIST = False (default)
- If a tag is in Excel but has no DB path mapping: flagged as NOT_FOUND in report

## Families Supported — Brew (SysConfig_Lib_Brew.db)
| Excel Column | Family    | MachineConfig Index | TypeNo |
|---|---|---|---|
| E (BREW 350)  | BREW350   | 7  | 7  |
| F (BREW 450)  | BREW450   | 8  | 8  |
| G (BREW 600)  | BREW600   | 9  | 9  |
| H (BREW 750H) | BREW750H  | 10 | 10 |
| I (BREW 600e) | BREW600e  | 11 | 11 |
| J (BREW 750e) | BREW750e  | 12 | 12 |
| K (BREW 750L) | BREW750L  | 13 | 13 |

## Families Pending — Clara / CR / PP / KR
These products are configured in `jobs.json` but mc_idx → family name mapping requires
HSS documentation to confirm. Once known, fill the `"families"` dict in jobs.json:

| Product | DB File                  | Excel Columns           | MC Indices (TypeNo)              |
|---|---|---|---|
| Clara   | SysConfig_Lib_Clara.db   | CLARA 400…CLARA 750H    | MC[0–14] (TypeNo 20–34)          |
| CR      | SysConfig_Lib_CR.db      | CR 450/750              | MC[0]=40, MC[2]=42, MC[3]=43     |
| PP      | SysConfig_Lib_PP.db      | PP 450/750              | MC[0]=50, MC[2]=52, MC[3]=53     |
| KR      | SysConfig_Lib_KR.db      | KR 400                  | MC[0]=60, MC[1]=61               |

## Output Files (per product)
| Product | Comparison Report       | Updated DB                      |
|---|---|---|
| Brew    | Brew_Comparison.xlsx    | SysConfig_Lib_Brew_updated.db   |
| Clara   | Clara_Comparison.xlsx   | SysConfig_Lib_Clara_updated.db  |
| CR      | CR_Comparison.xlsx      | SysConfig_Lib_CR_updated.db     |
| PP      | PP_Comparison.xlsx      | SysConfig_Lib_PP_updated.db     |
| KR      | KR_Comparison.xlsx      | SysConfig_Lib_KR_updated.db     |

Each comparison report has:
- Fixed columns: Tag Label, Function, Unit (e.g. "Unit Sep"), EM Module (e.g. "EM - 100")
- Per-family columns (16 per family):
  `Excel Val | Type | Exp EN | Exp EX | Exp VF | Exp NO | Exp FBOPN | Exp FBCLS | DB EN | DB EX | DB VF | DB NO | DB FBOPN | DB FBCLS | Match | Action`

## How to Run

### Prerequisites
- Close any open `.xlsx` files before running (Windows file lock)

### Brew (ready)
```
python run.py Brew
```

### All configured products
```
python run.py
```

### List job status
```
python run.py --list
```

### Add a new product or family
1. Add the new family column to `testLBB.xlsx` (header must match the key in jobs.json exactly)
2. Add/update the job entry in `jobs.json` — set `"families": {"Family Name": mc_idx, ...}`
3. Run `python run.py <JobName>` — no code changes needed

### Legacy single-product script
`main.py` still works for Brew only with hardcoded TAG_MAP (kept for reference).
New work should use `run.py` + `jobs.json`.
