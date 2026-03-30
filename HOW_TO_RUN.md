# HOW_TO_RUN.md — Running the DB Cross-Check Tool

## Prerequisites
- Python installed and available as `python` in terminal
- Working directory: `c:\Users\Administrator\Documents\Agentic World\TestDB`
- All `.xlsx` comparison files **closed in Excel** before running (Windows file lock)

---

## Run Commands

### Check job status
```
python run.py --list
```
Shows all jobs, which are READY (have families configured) and which are PENDING.

### Run a single job
```
python run.py Brew
python run.py Clara
python run.py CR
python run.py KR
python run.py PP
```

### Run all jobs at once
```
python run.py
```

---

## Output Files (per job)

| Job   | Comparison Report       | Updated DB                      |
|-------|-------------------------|---------------------------------|
| Brew  | Brew_Comparison.xlsx    | SysConfig_Lib_Brew_updated.db   |
| Clara | Clara_Comparison.xlsx   | SysConfig_Lib_Clara_updated.db  |
| CR    | CR_Comparison.xlsx      | SysConfig_Lib_CR_updated.db     |
| KR    | KR_Comparison.xlsx      | SysConfig_Lib_KR_updated.db     |
| PP    | PP_Comparison.xlsx      | SysConfig_Lib_PP_updated.db     |

- **`_Comparison.xlsx`** — full mismatch report, open in Excel to review
- **`_updated.db`** — corrected DB ready to import into TIA Portal 18

---

## Action Column Meanings in the Report

| Value | Meaning |
|-------|---------|
| `OK` | DB value already matches Excel spec — no change needed |
| `UPDATE: ENABLE/EXIST/VLV_W_FB: DB=X->Y` | DB was wrong, corrected in updated .db |
| `NOT FOUND IN DB` | Instrument mapped but path not found in DB |
| `NOT IN DB MAP` | Excel row has no matching instrument in the DB TYPE blocks |

---

## Adding a New Family to an Existing Product

Example: add **BREW 800** to the Brew job.

**Step 1** — Add the column to `testLBB.xlsx`
- Add a new column header exactly: `BREW 800`
- Fill in `X`, `o`, or empty for each instrument row

**Step 2** — Find the `mc_idx` from the DB
Open `SysConfig_Lib_Brew.db`, search for `TypeNo :=`:
```
MachineConfig[14].Machine.TypeNo := 14;
```
The array index `14` is your `mc_idx`.

**Step 3** — Edit `jobs.json`, add one line to the Brew `families` block:
```json
"families": {
  "BREW 350":  7,
  "BREW 450":  8,
  "BREW 800":  14
}
```
> The key `"BREW 800"` must match the Excel column header exactly.

**Step 4** — Run
```
python run.py Brew
```

---

## Adding a New Product (new .db file)

Example: add **Protein** with file `SysConfig_Lib_Protein.db`.

**Step 1** — Copy the `.db` file into the TestDB folder

**Step 2** — Find the `mc_idx` values inside the DB
Open the file, search for `TypeNo :=`:
```
MachineConfig[0].Machine.TypeNo := 70;   <- mc_idx = 0
MachineConfig[1].Machine.TypeNo := 71;   <- mc_idx = 1
```
Cross-reference TypeNo with HSS documentation to get the model name (e.g. `PROTEIN 400`).

**Step 3** — Add columns to `testLBB.xlsx`
Add one column header per family (e.g. `PROTEIN 400`, `PROTEIN 600`).
Fill in `X`, `o`, or empty for each instrument row.

**Step 4** — Add a new job entry to `jobs.json`:
```json
{
  "name": "Protein",
  "db": "SysConfig_Lib_Protein.db",
  "excel": "testLBB.xlsx",
  "families": {
    "PROTEIN 400": 0,
    "PROTEIN 600": 1
  },
  "out_db":   "SysConfig_Lib_Protein_updated.db",
  "out_xlsx": "Protein_Comparison.xlsx"
}
```

**Step 5** — Run
```
python run.py Protein
```

---

## Key Rules

| Rule | Detail |
|------|--------|
| Excel header must match exactly | `"BREW 800"` in jobs.json must be identical to the column header in testLBB.xlsx — same spelling, spaces, capitalisation |
| Close xlsx before running | Windows locks open Excel files — close all `_Comparison.xlsx` files before running |
| mc_idx comes from the DB | Look for `MachineConfig[N].Machine.TypeNo` in the .db file to find the index |
| No code changes needed | Everything is driven by `jobs.json` + `testLBB.xlsx` — no Python editing required |

---

## Current Job Configuration

Defined in `jobs.json`:

| Job   | DB File                  | Families                                              |
|-------|--------------------------|-------------------------------------------------------|
| Brew  | SysConfig_Lib_Brew.db    | BREW 350(7), BREW 450(8), BREW 600(9), BREW 750H(10), BREW 600e(11), BREW 750e(12), BREW 750L(13) |
| Clara | SysConfig_Lib_Clara.db   | CLARA 400(9), CLARA 400S(10), CLARA 450(11), CLARA 600(12), CLARA 600D(13), CLARA 750H(14) |
| CR    | SysConfig_Lib_CR.db      | CR 450(2), CR 750(3) |
| KR    | SysConfig_Lib_KR.db      | KR 400(1) |
| PP    | SysConfig_Lib_PP.db      | PP 450(2), PP 750(3) |

Numbers in parentheses are the `mc_idx` (MachineConfig array index) in the DB.
