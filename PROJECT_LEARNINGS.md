# TIA Portal Brew DB Checker — Project Learnings & Reference

> **Purpose:** Capture every technical insight, gotcha, and design decision from this project so the next iteration can build on solid ground without re-discovering the same problems.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Siemens TIA Portal DB Format](#2-siemens-tia-portal-db-format)
3. [CW (Control Word) Bit Layout](#3-cw-control-word-bit-layout)
4. [Excel Specification Structure](#4-excel-specification-structure)
5. [Processing Rules (Business Logic)](#5-processing-rules-business-logic)
6. [Architecture & Data Flow](#6-architecture--data-flow)
7. [Key Technical Learnings & Bugs Fixed](#7-key-technical-learnings--bugs-fixed)
8. [Python Libraries & Why](#8-python-libraries--why)
9. [TAG_MAP — The Central Mapping Layer](#9-tag_map--the-central-mapping-layer)
10. [How to Extend the Project](#10-how-to-extend-the-project)
11. [Known Limitations & Future Work](#11-known-limitations--future-work)
12. [Quick-Reference Cheatsheet](#12-quick-reference-cheatsheet)

---

## 1. Project Overview

**What it does:** Cross-checks a Siemens TIA Portal 18 Data Block (DB) export against a hardware specification Excel file to verify that each instrument's `ENABLE`, `EXIST`, and `VLV_W_FB` booleans are set correctly for each machine family.

**Why it exists:** Manually checking ~137 instruments per family across multiple families against a DB file is error-prone and time-consuming. A single run of `python run.py` replaces hours of manual work and eliminates human error.

**Outputs:**
| File | Purpose |
|------|---------|
| `SysConfig_Lib_Brew_updated.db` | Corrected DB ready for TIA Portal import |
| `InstrumentStatusComparison.xlsx` | Full comparison report with match/mismatch per instrument |

**Families:**
| Excel Column | Family Name | MachineConfig Index |
|---|---|---|
| E | BREW 350 | 7 |
| F | BREW 450 | 8 |

---

## 2. Siemens TIA Portal DB Format

### What a `.db` export looks like

TIA Portal exports Data Blocks as **UTF-8 plain text**. The file has two major sections:

```
TYPE "EM - 100"
  STRUCT
    EMS { ... } : "STAT DI" := ('EMS', ((), (), (), True, ...), ...);
    UPS         : "STAT DI" := ('UPS', ((), (), (), True, ...), ...);
    ...
  END_STRUCT;
END_TYPE

DATA_BLOCK "SysConfig_Lib_Brew"
  ...
BEGIN
  MachineConfig[7]."Unit Sep"."EM - 100".EMS.CW.ENABLE := True;
  MachineConfig[7]."Unit Sep"."EM - 100".EMS.CW.EXIST  := True;
  MachineConfig[8]."Unit Sep"."EM - 100".EWON.CW.ENABLE := True;
  ...
END_DATA_BLOCK
```

### Key structural facts

- **`TYPE "EM - xxx"` blocks** define the *type default* values for every instrument in that EM module. These are parsed with `parse_type_defaults()`.
- **`BEGIN ... END_DATA_BLOCK` section** contains *instance overrides* for each `MachineConfig[N]`. These are parsed with `parse_mc_overrides(db_text, mc_idx)`.
- **Effective value = override (if present) else type default.** Never assume the type default is False — always parse it.
- **Line endings are `\r\n` (Windows CRLF).** The script preserves this when writing the updated DB.
- **Field names with spaces or special chars** (e.g., `"P+F PS"`, `"LT BUF"`) are quoted in the DB: `"P+F PS".CW.ENABLE`. The script's `make_db_line()` automatically adds quotes when needed.
- **Boolean literals in TIA Portal DB files:** `True` / `False` (capital-first). The script normalises case-insensitively when reading.

### Path key convention

Every instrument is uniquely identified by the triple `(unit, em, field)`, stored as a pipe-separated string:

```python
def path_key(unit, em, field):
    return f"{unit}|{em}|{field}"
# e.g. "Unit Sep|EM - 100|EMS"
```

This key is used as the dict key throughout the entire pipeline.

---

## 3. CW (Control Word) Bit Layout

The CW (Control Word) is a 16-bit packed boolean struct. In the DB export it looks like a 16-element tuple:

```
((), (), (), True, (), (), TRUE, TRUE, (), (), (), (), (), True, (), True)
 b0   b1   b2   b3   b4   b5   b6    b7   b8   b9  b10  b11  b12  b13  b14  b15
```

**Critical bits:**

| Bit | Index | Field | Applicable to |
|-----|-------|-------|---------------|
| 3 | `bits[3]` | `ENABLE` | All STAT types |
| 13 | `bits[13]` | `EXIST` | All STAT types |
| 15 | `bits[15]` | `VLV_W_FB` | STAT VLV only |

**Parsing rule:** `()` = `False`, `True`/`TRUE` = `True`. Any other token defaults to `False`.

**Why a bracket-depth parser was needed:** The CW tuple is *nested* — it sits inside an outer constructor tuple. A naive regex like `\(([^)]+)\)` fails catastrophically because `[^)]+` stops at the first `)` inside nested parens. The fix was `extract_tuple_content()` which counts bracket depth:

```python
def extract_tuple_content(text, start_pos):
    depth = 0
    for i in range(start_pos, len(text)):
        if text[i] == "(": depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start_pos + 1 : i]
    return text[start_pos + 1:]
```

---

## 4. Excel Specification Structure

**File:** `testLBB.xlsx`, Sheet1

| Column | Content |
|--------|---------|
| B | Tag Label (e.g. `AV201-1`, `eWON`) |
| C | Function (e.g. `FB OPN`, `FB CLS`, `ACT`, `ENABLE`) |
| D | BREW 350 value (`X`, `o`, or empty) |
| E | BREW 450 value (`X`, `o`, or empty) |

- **Header row** is row 2. Data starts at row 3.
- **SPARE / DUMMY rows** are skipped.
- **Cell comments** on value cells (D/E column) give the **resolved tag name** used in the DB. Example: cell D130 has comment `PCV220-1`, meaning BREW350 uses `PCV220-1` instead of the label `PCV22X-1`. The script extracts these automatically with `openpyxl`.

### Comment extraction gotcha

Cell comments in TIA Portal-related Excel files may contain boilerplate prefixes (e.g., "Excel Comment: Threaded version X.X"). The script filters these out and takes the **last meaningful line** (not containing keywords like `http`, `version`, `learn`, `excel`, `comment:`, `threaded`).

---

## 5. Processing Rules (Business Logic)

### Excel value → ENABLE / EXIST

| Cell value | ENABLE | EXIST | Notes |
|------------|--------|-------|-------|
| `X` or `x` | True | True | Always |
| `o` or `O` | True | False | Standard rule |
| `o` (option-type tag) | False | False | See Option Override Rule below |
| empty / None | False | False | |
| `SPARE` | skip row | — | Row skipped entirely |

### Option Module Rule

If a tag's DB path is under **`Options."EM - XXX"`** (unit == `"Options"` in auto-discovered tag map):
- **ENABLE = False, EXIST = False** — unconditionally, Excel value is ignored.
- VLV_W_FB, FB_OPN_EN, FB_CLS_EN, NO — follow **normal logic** (not forced to False).

**Why only ENABLE/EXIST:** Option modules are physically not installed (EXIST=False). But their feedback configuration and type (NO/NC) should still reflect the hardware spec for completeness and TIA Portal correctness.

**Implementation:** `option_tags = {tag for tag, info in tag_map.items() if info[0] == "Options"}`. Only `xlval()` short-circuits to (False, False) when `is_option=True`. FB and NO follow standard rules.

### AV Valve multi-row processing

Each `AV` valve has **three rows** in Excel:

| Function (col C) | Purpose |
|-----------------|---------|
| `FB OPN` | Feedback Open — used for VLV_W_FB |
| `FB CLS` | Feedback Close — used for VLV_W_FB |
| `ACT` | Actuator — used for ENABLE / EXIST |

Rules:
- `ENABLE` / `EXIST` come from the **ACT row** for that valve
- `VLV_W_FB = True` if **either** FB OPN **or** FB CLS is `x`/`o`; `False` if both are empty
- Detection: `tag_label.upper().startswith("AV")` AND `func.upper() in {"FB OPN", "FB CLS", "ACT"}`

### Non-valve instruments

Single row. The cell value directly determines ENABLE/EXIST. VLV_W_FB is always False.

### Effective DB value

```
effective = MachineConfig[N] override  (if override exists for this field)
          else type definition default  (parsed from TYPE block)
          else False, False             (not found in DB at all)
```

### Minimal patch rule

Only write a `CW.ENABLE/EXIST/VLV_W_FB` override line in the updated DB when:

```
expected_value != type_default_value
```

This keeps the DB clean and avoids duplicating defaults. The script strips all existing CW override lines for the target MachineConfig indices and regenerates only the necessary ones.

---

## 6. Architecture & Data Flow

```
testLBB.xlsx ─────► parse_excel()
                          │
                          ▼ excel_data
                          │   {family: {tag: {enable, exist, vlv_w_fb, ...}}}
                          │
SysConfig_Lib_Brew.db ──► parse_type_defaults()
                          │   {path_key: {default_enable, default_exist, ...}}
                          │
                       ──► parse_mc_overrides(7)   ─► mc_overrides[7]
                       ──► parse_mc_overrides(8)   ─► mc_overrides[8]
                          │
                     compute_effective()
                          │   {path_key: {enable, exist, vlv_w_fb}}
                          │
                     build_comparison()
                          │   [{Tag Label, Unit, EM, BREW350_*, BREW450_*, ...}]
                          │
             ┌────────────┴─────────────────────────┐
             ▼                                        ▼
  generate_updated_db()                 write_comparison_xlsx()
  SysConfig_Lib_Brew_updated.db         InstrumentStatusComparison.xlsx
```

### Function responsibilities

| Function | Input | Output |
|----------|-------|--------|
| `parse_excel(path)` | xlsx path | `{family: {tag: instrument_dict}}` |
| `parse_type_defaults(db_text)` | raw DB string | `{path_key: default_dict}` |
| `parse_mc_overrides(db_text, mc_idx)` | raw DB string + index | `{path_key: override_dict}` |
| `compute_effective(defaults, overrides, tag)` | dicts + tag label | `(en, ex, vf, found)` tuple |
| `build_comparison(excel_data, defaults, overrides_all)` | all data | list of row dicts |
| `generate_updated_db(db_text, excel_data, defaults, overrides_all)` | all data | updated DB string |
| `write_comparison_xlsx(rows, out_path)` | comparison rows | writes xlsx |

---

## 7. Key Technical Learnings & Bugs Fixed

### 7.1 Nested parentheses — the CW tuple regex trap

**Problem:** The DB field default looks like:
```
'AV201-1', ((), (), (), True, (), (), ..., True, (), True)
```
Using `\(([^)]+)\)` to grab the CW content stopped at the first `)` inside the nested `()` elements, returning garbage.

**Fix:** `extract_tuple_content()` with bracket-depth counting (see Section 3). This is the single most important parser fix in the project.

**Lesson:** Any time you need to extract delimited content that may itself contain the delimiter, write a depth-counting walker — never use a greedy or negated-character regex.

---

### 7.2 Python operator precedence on ternary + `and`

**Problem:** This line silently misbehaved:
```python
vf_match = (exp_vf == eff_vf) if is_vlv if in_tag_map else True
```
Python parses the second `if` as a nested ternary, not as expected. The result was that `vf_match` evaluated strangely, causing all valves to appear as mismatches.

**Fix:**
```python
vf_match = (exp_vf == eff_vf) if (in_tag_map and is_vlv) else True
```

**Lesson:** Always parenthesise the condition of a Python ternary when it contains `and`/`or`. Never chain ternaries on the same line without explicit parentheses.

---

### 7.3 Similar precedence trap in the action block

**Problem:**
```python
if is_vlv if in_tag_map else False and not vf_match:
```
Python binds `and not vf_match` to `False`, making the condition always evaluate based on the ternary result alone. All valve-related VLV_W_FB corrections silently emitted blank `UPDATE:` strings.

**Fix:**
```python
if in_tag_map and is_vlv and not vf_match:
```

**Lesson:** Ternaries inside `if` conditions are a readability and correctness trap. Avoid them. Assign to a clearly named variable first.

---

### 7.4 Windows console UTF-8 crash

**Problem:** The script printed arrows (→) in f-strings for mismatch display. On Windows, the default console encoding is `cp1252`, causing `UnicodeEncodeError` on any non-ASCII character.

**Fix:** Add this at the very top of the script, before any print:
```python
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
```

**Lesson:** Always add this guard to any Python CLI script that may run on Windows and print non-ASCII output. Do it at the top, before imports that might print.

---

### 7.5 Field names with spaces or special characters

**Problem:** Some DB fields have names like `"P+F PS"`, `"LT BUF"`, `"P+F ERROR"`. The regex pattern `[A-Za-z0-9_\-\+\./]+` used for field name matching does not capture spaces, so these fields were missed during type default parsing. However, they were still correctly written in the updated DB because `make_db_line()` quotes them.

**Partial mitigation:** The effective value fell back to `False` for the type default, but the CW patch still wrote the correct expected value. Verification confirmed correctness.

**Future fix:** Extend the `field_hdr_pat` regex to allow quoted field names:
```python
r'(?:"([^"]+)"|([A-Za-z0-9_\-\+\./]+))'  # quoted OR unquoted field name
```

---

### 7.6 Cell comment extraction from openpyxl

**Problem:** `openpyxl` reads `.comment.text` as the raw comment string, which may contain metadata lines from Excel's threaded comments system (e.g., author name, version tags).

**Fix:** Split on newlines, reverse-iterate the lines, and take the last line that does not match any metadata keyword:
```python
lines = [ln.strip() for ln in cell.comment.text.splitlines() if ln.strip()]
for ln in reversed(lines):
    if not any(x in ln.lower() for x in ("http", "version", "learn", "excel", "comment:", "threaded")):
        comment = ln
        break
```

---

### 7.7 CW_VLV vs CW_AN — two distinct Control Word structures

AV valves use `CW_VLV`; all other STAT types use `CW_AN`. The bit positions differ:

**CW_VLV** (STAT VLV — AV valves):
| Bit | Field      | Notes |
|-----|------------|-------|
| 3   | ENABLE     | Master enable |
| 6   | FB_CLS_EN  | Enable Close Feedback |
| 7   | FB_OPN_EN  | Enable Open Feedback |
| 12  | NO         | `// NO/NC` |
| 13  | EXIST      | Valve exist |
| 15  | VLV_W_FB   | Valve Without Position Feedback |

**CW_AN** (STAT DI/DO/AI/AO/MTR/VFD — all non-valve instruments):
| Bit | Field  | Notes |
|-----|--------|-------|
| 3   | ENABLE | Master enable |
| 12  | NO     | `// 0=NC, 1=NO` |
| 13  | EXIST  | Exist |

**Key rule:** Bits 6, 7, 15 are VLV-only. The script gates these on `is_vlv`.

### 7.8 NO bit logic — NC/NO output type from Excel Type column

The `Type` column in `testLBB.xlsx` (header = "Type") holds the instrument output type:
- `NC` = Normally Closed output → `CW.NO = False`  (bit value 0 = NC)
- `NO` = Normally Open output → `CW.NO = True`    (bit value 1 = NO)
- `4..20MA` / empty → no override (keep type default)

**DB comment:** `NO : Bool // 0=NC, 1=NO` — the bit directly encodes the output type.
NC instruments use bit=0 (False); NO instruments use bit=1 (True).

### 7.9 FB_OPN_EN and FB_CLS_EN — feedback enable bits

These bits enable/disable position feedback monitoring for AV valves.
- `FB_OPN_EN` (bit 7): set True when FB OPN cell = x or o in Excel
- `FB_CLS_EN` (bit 6): set True when FB CLS cell = x or o in Excel
- `VLV_W_FB` (bit 15): True when either FB_OPN_EN or FB_CLS_EN is True

**Relation:** VLV_W_FB = FB_OPN_EN OR FB_CLS_EN. All three are derived from the same FB OPN / FB CLS column values.

---

## 8. Python Libraries & Why

| Library | Version | Usage | Notes |
|---------|---------|-------|-------|
| `openpyxl` | ≥3.1 | Read `testLBB.xlsx` including cell comments | `values_only=False` required to access `.comment` on cells |
| `xlsxwriter` | ≥3.1 | Write `InstrumentStatusComparison.xlsx` | Better formatting control than openpyxl write mode; supports cell formats, merges, freeze panes |
| `re` | stdlib | Parse DB TYPE blocks and CW override lines | Multiline / DOTALL flags required for TYPE blocks |
| `collections.defaultdict` | stdlib | Group valve rows; accumulate overrides per path_key | Avoids KeyError on first access |
| `io`, `sys` | stdlib | UTF-8 stdout wrapper on Windows | See Section 7.4 |

**Why not pandas for Excel reading?** Cell comments are not accessible through pandas — only openpyxl exposes `.comment.text` on individual cells.

**Why xlsxwriter and not openpyxl for writing?** xlsxwriter has a richer format API (colors, borders, merges, freeze panes, column widths) and is write-only (lower memory). openpyxl write mode requires loading the full workbook model.

---

## 9. Auto-Discovery of Tag Map (run.py)

`run.py` eliminates the manual TAG_MAP entirely. `build_tag_map(db_text)` does this in two steps:

**Step 1 — derive em → unit** by scanning any `MachineConfig[N]."unit"."em".` path that appears
anywhere in the DB BEGIN section. This doesn't require knowing which MC index to use — any path
in the file reveals the em→unit relationship:

```python
em_unit = {}
for m in re.finditer(r'MachineConfig\[\d+\]\."([^"]+)"\."([^"]+)"\.', db_text):
    em_unit[m.group(2)] = m.group(1)   # em_name → unit_name (last occurrence wins)
```

**Step 2 — scan TYPE blocks** for instrument fields typed with STAT VLV/DI/DO/AI/AO/MTR/VFD:

```python
for each TYPE "EM-xxx" block:
    for each field: "STAT VLV/DI/..." :=
        tag_map[field_name] = (unit, em, field_name, is_vlv)
```

**Why this works:** All 5 DBs (Brew, Clara, CR, KR, PP) share the same 30 `TYPE "EM-XXX"` block
definitions. The auto-discovery is identical for all products — only the `families` dict in
`jobs.json` changes per product.

**Multi-product operation:** Configure `jobs.json` once, then run any product with:
```
python run.py Brew       # or Clara, CR, PP, KR
python run.py            # run all
```

**Special characters in field names:** Field names containing parentheses or hyphens (e.g.
`LS42X(b)`) must be **quoted** when written to the DB so the parser can find them back:
```python
def q(s):
    return f'"{s}"' if re.search(r'[^A-Za-z0-9_]', s) else s
```
Original bug: only `[\s\-\+/]` triggered quoting, so `LS42X(b)` was written unquoted but couldn't
be found by `parse_mc_overrides` — causing 7 verify failures until fix.

---

## 10. How to Extend the Project

### Using run.py (recommended)

**Add a new machine family to an existing product:**
1. Add a column to `testLBB.xlsx` — the column header must match exactly what you'll put in jobs.json
2. Open `jobs.json`, add the family to the relevant job's `"families"` dict: `"NEW FAMILY": mc_idx`
3. Run `python run.py <JobName>` — no code changes needed

**Add a new product (e.g. new .db file):**
1. Add a new job entry in `jobs.json`:
   ```json
   {"name": "NewProduct", "db": "SysConfig_Lib_New.db", "excel": "testLBB.xlsx",
    "families": {"FAMILY X": 0}, "out_db": "SysConfig_Lib_New_updated.db",
    "out_xlsx": "New_Comparison.xlsx"}
   ```
2. Run `python run.py NewProduct` — tag map is auto-discovered from the DB

**Swap to a new DB version:**
1. Drop the new `.db` file into the TestDB folder
2. Run `python run.py <JobName>` — re-parses from scratch

**Add a new instrument:**
- No code change needed. If the instrument is in the DB TYPE blocks as a STAT-typed field,
  `build_tag_map()` finds it automatically.

---

## 11. Known Limitations & Future Work

### Current limitations

| # | Issue | Impact | Suggested Fix |
|---|-------|--------|---------------|
| 1 | Field names with spaces missed during type default parsing | Type default falls back to False; patch still correct | Extend `field_hdr_pat` regex to capture quoted field names |
| 2 | ~47 instruments per family show `NOT IN TAG_MAP` | These are unmapped SPARE/special-function rows or instruments not yet added | Review Excel rows and map the meaningful ones |
| 3 | Script only processes Sheet1 of testLBB.xlsx | Multi-sheet layouts would require `wb.worksheets` iteration | Low priority unless layout changes |
| 4 | No GUI / web interface | Requires Python environment to run | Could be wrapped in a simple Flask UI or a batch script for non-technical users |
| 5 | VLV_W_FB comparison is skipped for non-valve instruments | Correct by design, but silently | No change needed |

### Potential improvements

- **Auto-detect unmapped rows** by scanning the Excel for tags not found in the auto-discovered tag map and printing a warning list, so coverage gaps are obvious.
- **Summary tab in xlsx** showing totals by Unit/EM module (how many OK vs MISMATCH per EM).
- **Diff mode** — compare two DB versions against the same Excel to see what changed between DB exports.
- **CI/CD integration** — run `python run.py` as part of a GitHub Actions workflow on push of a new `.db` file.

---

## 12. MachineConfig Index (mc_idx) Reference

### How TypeNo works
- `TypeNo` in the DB is the **HSS (Hardware Specification Sheet) ID number** — Alfa Laval's internal serial identifier for a machine variant.
- The DB has **no human-readable name** stored for each index. The mapping to "BREW 350", "BREW 450" etc. comes from Alfa Laval's HSS documentation and the Excel column headers.
- `mc_idx` always equals `TypeNo` — `MachineConfig[7]` has `TypeNo := 7`.

### MachineConfig fields that help identify a machine
| DB Field | Comment | Values |
|---|---|---|
| `Family` | Machine product line | 1=Brew, 2=Clara, 3=CR, 4=PurePuls, 5=KR, 6=Protein, 7=VOT, 8=Dairy |
| `TypeNo` | **HSS ID** — equals mc_idx | 7, 8, 9, … |
| `Range` | Factory/size range | 1=TumbaL, 2=PuneS |
| `Frame` | Separator frame size | 1=18, 2=18e, 3=15, 4=13, 5=10, 6=07, 7=04, 8=LD |
| `DchSystem` | Discharge system type | 1=Dosing ring, 2=OWMC, 3=OWMCe, 4=OWM II |
| `eMotion` | eMotion option | 0=Not compatible, 1=Compatible, 2=Installed |

### Known Brew family mapping (SysConfig_Lib_Brew.db)
| mc_idx | TypeNo | Family Name   | Notes |
|---|---|---|---|
| 7  | 7  | **BREW 350**  | |
| 8  | 8  | **BREW 450**  | |
| 9  | 9  | **BREW 600**  | |
| 10 | 10 | **BREW 750H** | |
| 11 | 11 | **BREW 600e** | |
| 12 | 12 | **BREW 750e** | |
| 13 | 13 | **BREW 750L** | |

### Other Products — TypeNo Reference (mc_idx → TypeNo, family name from HSS)
| Product | DB                      | MC Indices   | TypeNo Range | Family Code |
|---|---|---|---|---|
| Clara   | SysConfig_Lib_Clara.db  | MC[0]–MC[14] | 20–34        | 2           |
| CR      | SysConfig_Lib_CR.db     | MC[0,2,3]    | 40, 42, 43   | 3           |
| PP      | SysConfig_Lib_PP.db     | MC[0,2,3]    | 50, 52, 53   | 4           |
| KR      | SysConfig_Lib_KR.db     | MC[0,1]      | 60, 61       | 5           |

> MC indices are 0-based. For Clara: MC[0]=TypeNo20, MC[1]=TypeNo21, …, MC[14]=TypeNo34.
> Family code 1=Brew, 2=Clara, 3=CR, 4=PurePuls, 5=KR (from DB comment).

> **To confirm mc_idx for a family:** Open the DB, find `MachineConfig[N].Machine.TypeNo := XX` and
> cross-reference TypeNo with the HSS document to get the human-readable model name (e.g. "CLARA 400").
> Then add `"CLARA 400": N` to the `"families"` dict in jobs.json.

---

## 13. Quick-Reference Cheatsheet

```
# === RECOMMENDED: run.py + jobs.json ===

cd "c:\Users\Administrator\Documents\Agentic World\TestDB"

python run.py --list        # show all jobs and their status
python run.py Brew          # run a specific job
python run.py               # run all jobs with families configured

# Outputs per job (example: Brew)
Brew_Comparison.xlsx             ← review mismatches (close before running)
SysConfig_Lib_Brew_updated.db    ← drop into TIA Portal

# To add a new family to an existing product
1. Add column to testLBB.xlsx (exact header = job key)
2. Edit jobs.json: add "Family Name": mc_idx to the job's "families" dict
3. python run.py <JobName>

# To enable Clara/CR/PP/KR: fill in "families" dict in jobs.json from HSS docs
# mc_idx values: Clara=MC[0-14]/TypeNo20-34, CR=MC[0,2,3]/TypeNo40,42,43
#                PP=MC[0,2,3]/TypeNo50,52,53, KR=MC[0,1]/TypeNo60,61

# CW bit positions (0-indexed)
bit 3  = ENABLE
bit 13 = EXIST
bit 15 = VLV_W_FB  (STAT VLV only)

# Excel value legend
X  → ENABLE=True,  EXIST=True
o  → ENABLE=True,  EXIST=False
   → ENABLE=False, EXIST=False

# Option tags (unit="Options" in DB): always ENABLE=EXIST=VLV_W_FB=False

# Valve rows in Excel (AV prefix)
FB OPN + FB CLS → VLV_W_FB
ACT             → ENABLE / EXIST

# Action column meanings in report
OK              → DB already matches Excel
UPDATE: ...     → DB has been corrected in updated.db
NOT IN TAG_MAP  → Excel row not in auto-discovered tag map
NOT FOUND IN DB → Mapped but path_key absent in DB
```

---

*Updated March 2026 — extended to universal multi-product runner (run.py + jobs.json).*
*Covers Brew (all 7 families), with Clara/CR/PP/KR pending HSS mc_idx confirmation.*
