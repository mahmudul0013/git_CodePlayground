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

**Why it exists:** Manually checking ~137 instruments per family across two families (BREW 350, BREW 450) against a DB file is error-prone and time-consuming. A single run of `python main.py` replaces hours of manual work and eliminates human error.

**Outputs:**
| File | Purpose |
|------|---------|
| `SysConfig_Lib_Brew_updated.db` | Corrected DB ready for TIA Portal import |
| `InstrumentStatusComparison.xlsx` | Full comparison report with match/mismatch per instrument |

**Families:**
| Excel Column | Family Name | MachineConfig Index |
|---|---|---|
| D | BREW 350 | 7 |
| E | BREW 450 | 8 |

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

**File:** `testBrew.xlsx`, Sheet1

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

### Option Module Override Rule

If any family cell for a tag contains one of these **option description** strings:
`BLENDING`, `RECIRCULATION`, `COOLING RECIRCULATION`, `SRU`, `FEED PUMP`
— the tag is classified as **option-type**.

For option-type tags, `o` in any family column means "option module not installed for this variant" → **ENABLE=False, EXIST=False** (overrides the standard `o` rule). `X` still gives True/True.

The same logic applies to VLV_W_FB: `o` on FB OPN/CLS rows of an option-type valve → VLV_W_FB=False.

**Two conditions — either triggers option-type classification:**
1. Excel "Option" column value is one of the OPTION_MARKERS (or legacy: family cell contains the marker)
2. Tag's `TAG_MAP` unit is `"Options"` — catches any EM found under `Options."EM-XXX"` in the DB (e.g. EM-463 eMotion instruments whose Option column says "E-MOTION")

**Implementation:** `option_tags` set is built inside `parse_excel()` before the aggregation loop. Both `xlval_to_enable_exist(val, is_option)` and `has_fb(fam_vals, fam_name, is_option)` accept an `is_option` flag.

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
testBrew.xlsx ─────► parse_excel()
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

### 7.7 VLV_W_FB is only meaningful for STAT VLV types

The bit at `bits[15]` physically exists in all CW tuples in the file but only has semantic meaning for `STAT VLV` typed instruments. For DI/DO/AI/AO/MTR/VFD types it is irrelevant. The script checks `is_vlv` (set when `stat_type == "STAT VLV"`) before including VLV_W_FB in comparison or patch output.

---

## 8. Python Libraries & Why

| Library | Version | Usage | Notes |
|---------|---------|-------|-------|
| `openpyxl` | ≥3.1 | Read `testBrew.xlsx` including cell comments | `values_only=False` required to access `.comment` on cells |
| `xlsxwriter` | ≥3.1 | Write `InstrumentStatusComparison.xlsx` | Better formatting control than openpyxl write mode; supports cell formats, merges, freeze panes |
| `re` | stdlib | Parse DB TYPE blocks and CW override lines | Multiline / DOTALL flags required for TYPE blocks |
| `collections.defaultdict` | stdlib | Group valve rows; accumulate overrides per path_key | Avoids KeyError on first access |
| `io`, `sys` | stdlib | UTF-8 stdout wrapper on Windows | See Section 7.4 |

**Why not pandas for Excel reading?** Cell comments are not accessible through pandas — only openpyxl exposes `.comment.text` on individual cells.

**Why xlsxwriter and not openpyxl for writing?** xlsxwriter has a richer format API (colors, borders, merges, freeze panes, column widths) and is write-only (lower memory). openpyxl write mode requires loading the full workbook model.

---

## 9. TAG_MAP — The Central Mapping Layer

`TAG_MAP` is the single lookup table that bridges Excel tag labels to DB paths:

```python
TAG_MAP = {
    "AV201-1": ("Unit Process", "EM - 201", "AV201-1", True),
    #  Excel label │  Unit          │  EM module │  DB field  │ is_vlv
}
```

**Fields:**
1. `unit` — the unit name as it appears in the DB (e.g. `"Unit Sep"`, `"Unit Process"`, `"Unit Dch"`, `"Options"`)
2. `em` — the EM type name as it appears in `TYPE "EM - xxx"` blocks (e.g. `"EM - 100"`)
3. `db_field` — the exact field name inside that EM type (case-sensitive, must match the DB)
4. `is_vlv` — `True` if this is a `STAT VLV` type (has meaningful VLV_W_FB bit)

**When `NOT IN TAG_MAP`:** The comparison report shows `NOT IN TAG_MAP` in the Action column. The instrument is still listed (from Excel) but no DB comparison or patch is attempted.

**When `NOT FOUND IN DB`:** The tag is in TAG_MAP but its path_key is not in either `type_defaults` or `mc_overrides`. Effective value defaults to False/False.

**Maintenance:** Add a new row to TAG_MAP whenever a new instrument is added to the Excel. The unit/em/db_field values must match the DB export exactly — including case.

---

## 10. How to Extend the Project

### Add a new machine family

1. Add a column to `testBrew.xlsx` (e.g. column F = BREW 550)
2. Add an entry to `FAMILIES` in `main.py`:
   ```python
   FAMILIES = {
       "BREW 350": {"mc_idx": 7, "col_idx": 4},
       "BREW 450": {"mc_idx": 8, "col_idx": 5},
       "BREW 550": {"mc_idx": 9, "col_idx": 6},   # ← new
   }
   ```
3. Run `python main.py` — all other code adapts automatically.

### Add a new instrument

1. Add the row(s) to `testBrew.xlsx` (tag label in col B, function in col C, values in D/E/etc.)
2. Add to `TAG_MAP` in `main.py`:
   ```python
   "NewTag-1": ("Unit Sep", "EM - 400", "NewTag-1", True),
   ```
3. If the instrument belongs to a new EM module, add the module to `EM_UNIT_MAP` inside `parse_type_defaults()`.
4. Run `python main.py`.

### Swap to a new DB version

1. Drop the new `.db` file into the TestDB folder (overwrite or rename `DB_PATH`)
2. Run `python main.py` — type defaults and overrides are re-parsed from scratch.

### Add a new EM module to the DB parser

In `parse_type_defaults()`, add an entry to `EM_UNIT_MAP`:
```python
EM_UNIT_MAP = {
    ...
    "EM - 999": "Unit Sep",   # ← new module
}
```

---

## 11. Known Limitations & Future Work

### Current limitations

| # | Issue | Impact | Suggested Fix |
|---|-------|--------|---------------|
| 1 | Field names with spaces missed during type default parsing | Type default falls back to False; patch still correct | Extend `field_hdr_pat` regex to capture quoted field names |
| 2 | ~47 instruments per family show `NOT IN TAG_MAP` | These are unmapped SPARE/special-function rows or instruments not yet added | Review Excel rows and map the meaningful ones |
| 3 | Script only processes Sheet1 of testBrew.xlsx | Multi-sheet layouts would require `wb.worksheets` iteration | Low priority unless layout changes |
| 4 | No GUI / web interface | Requires Python environment to run | Could be wrapped in a simple Flask UI or a batch script for non-technical users |
| 5 | VLV_W_FB comparison is skipped for non-valve instruments | Correct by design, but silently | No change needed |

### Potential improvements

- **Auto-detect new TAG_MAP entries** by scanning the Excel for tags not already in `TAG_MAP` and printing a warning list, so maintenance is obvious.
- **Summary tab in xlsx** showing totals by Unit/EM module (how many OK vs MISMATCH per EM).
- **Diff mode** — compare two DB versions against the same Excel to see what changed between DB exports.
- **CI/CD integration** — run `python main.py` as part of a GitHub Actions workflow on push of a new `.db` file.
- **Config file** — move `FAMILIES`, `DB_PATH`, `EXCEL_PATH` out of `main.py` into a `config.json` or `.env` so non-coders can configure without editing Python.

---

## 12. Quick-Reference Cheatsheet

```
# Run the full pipeline
cd "c:\Users\Administrator\Documents\Agentic World\TestDB"
python main.py

# Outputs produced
SysConfig_Lib_Brew_updated.db       ← drop into TIA Portal
InstrumentStatusComparison.xlsx     ← review mismatches

# CW bit positions (0-indexed)
bit 3  = ENABLE
bit 13 = EXIST
bit 15 = VLV_W_FB  (STAT VLV only)

# Excel value legend
X  → ENABLE=True,  EXIST=True
o  → ENABLE=True,  EXIST=False
   → ENABLE=False, EXIST=False

# Valve rows in Excel (AV prefix)
FB OPN + FB CLS → VLV_W_FB
ACT             → ENABLE / EXIST

# Action column meanings in report
OK              → DB already matches Excel
UPDATE: ...     → DB will be corrected in updated.db
NOT IN TAG_MAP  → Excel row not mapped in TAG_MAP dict
NOT FOUND IN DB → Mapped but path_key absent in DB

# To add a new family
1. Add Excel column
2. Add entry to FAMILIES dict
3. python main.py

# To add a new instrument
1. Add row to Excel
2. Add entry to TAG_MAP
3. python main.py
```

---

*Document generated from the BREW 350 / BREW 450 implementation — March 2026.*
*All rules and findings apply equally to any future Brew family variant.*
