# EnvoraSiemens_Skill.md
## Project Rules, Domain Knowledge & Skill Reference
### TIA Portal DB Cross-Check Tool — Envora / Alfa Laval

---

## 1. Project Purpose

Cross-check Siemens TIA Portal 18 Data Block (DB) exports against hardware specification Excel
(`testLBB.xlsx`) to verify instrument configuration booleans are set correctly per machine family.
Produces a corrected `.db` file (importable to TIA Portal) and a comparison report `.xlsx`.

**Run command:**
```
cd "c:\Users\Administrator\Documents\Agentic World\TestDB"
python run.py Brew          # single product
python run.py               # all products
python run.py --list        # check status
```

---

## 2. Siemens TIA Portal DB File Structure

```
TYPE "EM - 100"           ← Equipment Module type definition (default values)
  STRUCT
    EMS : "STAT DI" := ('EMS', (b0, b1, ..., b15), ...);
  END_STRUCT;
END_TYPE

DATA_BLOCK "SysConfig_Lib_Brew"
BEGIN
  MachineConfig[7]."Unit Sep"."EM - 100".EMS.CW.ENABLE := True;   ← instance override
  MachineConfig[7].Options."EM - 208"."AV208-1".CW.NO := True;    ← Options = unquoted!
END_DATA_BLOCK
```

**Key facts:**
- `TYPE` blocks = type defaults. `BEGIN...END_DATA_BLOCK` = per-MachineConfig instance overrides.
- Effective value = instance override if present, else type default.
- Line endings = `\r\n` (Windows CRLF) — preserve on write.
- Unit names: quoted (`"Unit Sep"`) OR **unquoted** (`Options`, `Communications`, `Machine`).
  The `Options` unit is always unquoted — this is critical for regex matching.
- `()` in CW tuple = `False`; `True`/`TRUE` = `True`.
  Handled by `parse_cw_bits()` — every `()` element appends `False`, every `TRUE`/`True` appends `True`.
  The CW tuple is always the second element after the tag name string, e.g.:
  `('AV208-1', ((), (), (), (), (), (), TRUE, TRUE, ..., TRUE), ...)` → bits[3]=False, bits[6]=True, bits[7]=True, bits[15]=True.

---

## 3. CW Control Word Bit Layouts

### CW_VLV (STAT VLV — AV valves)
| Bit | Field      | Description                       |
|-----|------------|-----------------------------------|
| 0   | AUTO_CMD   | Auto command                      |
| 1   | FORCE      | Force command                     |
| 3   | ENABLE     | Master enable                     |
| 4   | FB_CLS     | Feedback Close (status)           |
| 5   | FB_OPN     | Feedback Open (status)            |
| 6   | FB_CLS_EN  | Enable Close Feedback (setpoint)  |
| 7   | FB_OPN_EN  | Enable Open Feedback (setpoint)   |
| 12  | NO         | 0=NC output, 1=NO output          |
| 13  | EXIST      | Valve exists                      |
| 14  | OUT_ACT    | Output activation                 |
| 15  | VLV_W_FB   | Valve Without Position Feedbacks  |

### CW_AN (STAT DI/DO/AI/AO/MTR/VFD — all non-valve instruments)
| Bit | Field    | Description              |
|-----|----------|--------------------------|
| 3   | ENABLE   | Master enable            |
| 12  | NO       | 0=NC output, 1=NO output |
| 13  | EXIST    | Instrument exists        |

---

## 4. Excel Specification Rules

### Excel file: `testLBB.xlsx` — column layout
| Col | Content |
|-----|---------|
| B   | Tag Label |
| C   | Function (FB OPN / FB CLS / ACT / ENABLE / etc.) |
| D   | Option descriptor (e.g. BLENDING, RECIRCULATION) |
| E   | Type (NC / NO / 4..20MA) |
| F+  | Family columns (BREW 350, BREW 450, CLARA 400, …) |

### Cell value → ENABLE / EXIST
| Value | ENABLE | EXIST | Notes |
|-------|--------|-------|-------|
| `X` or `x` | True | True  | Installed and active |
| `o` or `O` | True | False | Present but passive  |
| empty/SPARE | False | False | Not installed |

### Type column → NO bit
| Type  | CW.NO | Meaning |
|-------|-------|---------|
| `NC`  | False | Normally Closed output (0=NC, bit=False) |
| `NO`  | True  | Normally Open output (1=NO, bit=True) |
| `4..20MA` / empty | no override | Keep type default |

**DB comment:** `NO : Bool // 0=NC, 1=NO` — bit directly encodes the output type.
NC → bit=0 (False); NO → bit=1 (True).

### AV Valve multi-row processing
Each AV valve has three Excel rows (identified by `tag_label.startswith("AV")` and `Function`):

| Function | Determines |
|----------|------------|
| FB OPN   | FB_OPN_EN = True if x/o; VLV_W_FB = True if x/o |
| FB CLS   | FB_CLS_EN = True if x/o; VLV_W_FB = True if x/o |
| ACT      | ENABLE / EXIST |

VLV_W_FB = FB_OPN_EN OR FB_CLS_EN.

### Cell comments → resolved tag name
If a value cell has a comment (e.g. cell comment = `PCV220-1`), the comment is the actual DB tag
label. The Excel label (e.g. `PCV22X-1`) is just a display alias.

---

## 5. Business Logic Rules

### Option Module Rule
If tag's DB unit = `"Options"` (EM lives under `Options."EM - XXX"` in the DB):
- **ENABLE = False, EXIST = False** — unconditionally, regardless of Excel value.
- VLV_W_FB, FB_OPN_EN, FB_CLS_EN, NO — follow normal logic.

Detection: `option_tags = {tag for tag, info in tag_map.items() if info[0] == "Options"}`

### Minimal Patch Rule
Only write a `CW.PROP := Value` line in the updated DB when:
`expected_value != type_default_value`
This keeps the DB clean and avoids duplicating defaults.

### Effective Value
`effective = MachineConfig[N] override (if exists) else TYPE block default else False`

---

## 6. Products and DB Files

| Product | DB File                  | Family Column | MC Indices |
|---------|--------------------------|---------------|------------|
| Brew    | SysConfig_Lib_Brew.db    | BREW 350–750L | MC[7–13]   |
| Clara   | SysConfig_Lib_Clara.db   | CLARA 400–750H| MC[9–14]   |
| CR      | SysConfig_Lib_CR.db      | CR 450, CR 750| MC[2–3]    |
| PP      | SysConfig_Lib_PP.db      | PP 450, PP 750| MC[2–3]    |
| KR      | SysConfig_Lib_KR.db      | KR 400        | MC[1]      |

Family code in DB: 1=Brew, 2=Clara, 3=CR, 4=PurePuls, 5=KR.
All 5 DBs share the same 30 `TYPE "EM-XXX"` block definitions.

---

## 7. Auto-Discovery — No Manual TAG_MAP

`build_tag_map(db_text)` in `run.py` does this in two steps:

**Step 1 — em → unit mapping** (handles both quoted and unquoted unit names):
```python
for m in re.finditer(
    r'MachineConfig\[\d+\]\.(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_]*))\."([^"]+)"\.',
    db_text
):
    unit = m.group(1) or m.group(2)
    em   = m.group(3)
    em_unit[em] = unit
```

**Step 2 — field discovery** from `TYPE "EM-xxx"` blocks:
```python
for each TYPE "EM-xxx" block:
    for each field with ": "STAT VLV/DI/..." :=":
        tag_map[field] = (unit, em, field, is_vlv)
```

**Critical:** `Options` unit is **unquoted** in DB paths. Without the `|([A-Za-z][A-Za-z0-9_]*)` 
alternation in the regex, all 5 Options EMs (EM-208, EM-210, EM-463, EM-551, EM-P201) get
mapped to `"Unknown"` instead of `"Options"`, and the Option Module Rule is never applied.

---

## 8. Configuration — jobs.json

```json
{
  "jobs": [
    {
      "name": "Brew",
      "db":    "SysConfig_Lib_Brew.db",
      "excel": "testLBB.xlsx",
      "families": { "BREW 350": 7, "BREW 450": 8, ... },
      "out_db":   "SysConfig_Lib_Brew_updated.db",
      "out_xlsx": "Brew_Comparison.xlsx"
    }
  ]
}
```

- `families` key = **exact** Excel column header (case-sensitive, spaces included).
- `families` value = `MachineConfig[N]` array index from the `.db` file.
- Jobs with `"families": {}` are skipped (shown as PENDING in `--list`).

**To add a family:** add `"New Family Name": mc_idx` to the job's families dict.
**To find mc_idx:** search `MachineConfig[N].Machine.TypeNo` in the DB file.
**To add a product:** add a new job block in jobs.json — no code changes needed.

---

## 9. Known Gotchas

| Issue | Symptom | Fix |
|-------|---------|-----|
| Options unit unquoted | Options EMs mapped to "Unknown", option rule never applied | Regex must handle both `"quoted"` and `unquoted` unit styles |
| Field names with special chars (e.g. `LS42X(b)`) | Verify fail after DB update | `q()` function quotes names with non-alphanumeric chars: `[^A-Za-z0-9_]` |
| Nested CW tuple | `\(([^)]+)\)` regex stops at first `)` inside nested `()` | Use bracket-depth walker `extract_tuple_content()` |
| Excel file locked | `PermissionError` on write | Close all `_Comparison.xlsx` files in Excel before running |
| Windows UTF-8 | `UnicodeEncodeError` for non-ASCII chars | Wrap stdout: `io.TextIOWrapper(..., encoding="utf-8")` |
| Python ternary precedence | `if is_vlv if in_map else True` parses wrong | Always parenthesise: `if (in_map and is_vlv)` |

---

## 10. Comparison Report — Action Column

| Value | Meaning |
|-------|---------|
| `OK` | DB value matches Excel spec — no change needed |
| `UPDATE: ENABLE/EXIST/VLV_W_FB/NO/FB_OPN_EN/FB_CLS_EN: DB=X->Y` | Corrected in updated .db |
| `NOT FOUND IN DB` | Instrument in DB tag map but path absent in DB |
| `NOT IN DB MAP` | Excel row has no matching instrument in DB TYPE blocks |
