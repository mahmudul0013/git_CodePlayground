# wishList.md

## Goal
Cross-check Siemens TIA Portal DB default values against hardware specification Excel.
Compare BREW350 (MachineConfig[7]) and BREW450 (MachineConfig[8]) families.
Produce an updated `.db` file importable directly into TIA Portal, plus a comparison report.

## Processing Rules

### Excel Tag Reading Rules (per family column)
- `X` or `x`  → ENABLE = True,  EXIST = True
- `o`          → ENABLE = True,  EXIST = False
- empty/SPARE  → ENABLE = False, EXIST = False

### Option Module Override Rule (higher priority than the standard `o` rule)
If a tag has an **option description** in any family column — one of:
`BLENDING`, `RECIRCULATION`, `COOLING RECIRCULATION`, `SRU`, `FEED PUMP` —
then for ALL families where that tag's value is `o`:
- ENABLE = False,  EXIST = False  _(module not selected for this machine variant)_

This applies to both ENABLE/EXIST (from ACT row for valves) and VLV_W_FB (FB OPN/CLS rows).
`X` still gives True/True regardless of option type.

### VLV_W_FB Logic (AV valves only, based on Function column)
- FB OPN or FB CLS = `x` → VLV_W_FB = True
- FB OPN or FB CLS = `o` (and **not** an option-type tag) → VLV_W_FB = True
- FB OPN or FB CLS = `o` (and tag **is** option-type) → VLV_W_FB = False
- Both FB OPN and FB CLS empty → VLV_W_FB = False

### Valve ENABLE/EXIST Source
- AV valves: ENABLE/EXIST determined by the **ACT** row for that valve
- VLV_W_FB determined by FB OPN / FB CLS rows

### Non-Valve ENABLE/EXIST Source
- Direct column value (BREW350 / BREW450 column) → ENABLE/EXIST

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

## Families Supported
| Excel Column | Family   | MachineConfig Index | TypeNo |
|---|---|---|---|
| D (BREW 350) | BREW350  | 7                   | 7      |
| E (BREW 450) | BREW450  | 8                   | 8      |

## Output Files
- `SysConfig_Lib_Brew_updated.db`  — updated DB importable to TIA Portal
- `InstrumentStatusComparison.xlsx` — full comparison report for all instruments
  - Fixed columns: Tag Label, Function, **Unit** (e.g. "Unit Sep"), **EM Module** (e.g. "EM - 100")
  - Per-family columns: Excel Val, Exp EN/EX/VF, DB EN/EX/VF, Match, Action

## Sustainable Operation
To reprocess a new family:
1. Update `testBrew.xlsx` with the new family column
2. Upload the new `.db` file
3. Run `python main.py` — everything is regenerated from scratch
