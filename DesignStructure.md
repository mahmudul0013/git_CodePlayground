# DesignStructure.md

## Architecture: Single-File Sustainable Pipeline

### Entry Point
`main.py` — run with `python main.py` from the TestDB folder.

### Processing Pipeline

```
testBrew.xlsx  ──► parse_excel()           ──► excel_data
                                                  │
SysConfig_Lib_Brew.db ──► parse_type_defaults()  ──► type_defaults
                       ──► parse_mc_overrides(N)  ──► mc_overrides[7], mc_overrides[8]
                                                  │
                      compute_effective_values()  ──► effective[7], effective[8]
                                                  │
                           compare()              ──► comparison_rows
                                                  │
                 ┌─────────────────┴───────────────────┐
                 ▼                                       ▼
    write_updated_db()                   write_comparison_xlsx()
    SysConfig_Lib_Brew_updated.db        InstrumentStatusComparison.xlsx
```

### Module Functions in main.py

#### `parse_excel(path)`
- Reads `testBrew.xlsx` Sheet1
- Resolves tag labels using value-cell comments (e.g. D130 comment → resolved tag)
- Detects **option-type tags**: any tag whose family cell value is one of
  `BLENDING | RECIRCULATION | COOLING RECIRCULATION | SRU | FEED PUMP`
  → for option-type tags, cell value `o` gives ENABLE=False, EXIST=False
    (instead of the normal True/False), and VLV_W_FB is also forced False on `o`
- Handles multi-row valve processing:
  - Collects FB OPN, FB CLS rows → VLV_W_FB
  - Collects ACT row → ENABLE/EXIST for valves
  - Single row for non-valves → ENABLE/EXIST
- Returns: `{family: {resolved_db_tag: {enable, exist, vlv_w_fb, excel_label, function}}}`

#### `parse_type_defaults(db_text)`
- Scans `TYPE ... END_TYPE` blocks in the DB
- Parses CW tuple `(b0..b15)` for each STAT VLV/DI/DO/AI/AO/MTR/VFD instance
  - bit 3 = ENABLE, bit 13 = EXIST, bit 15 = VLV_W_FB (VLV only)
- Builds the tag→path map from each EM type definition
- Returns: `{db_path_key: {default_enable, default_exist, default_vlv_w_fb, unit, em, field}}`

#### `parse_mc_overrides(db_text, mc_idx)`
- Finds all `MachineConfig[N].*.CW.(ENABLE|EXIST|VLV_W_FB) := (True|False)` lines
- Returns: `{db_path_key: {enable, exist, vlv_w_fb}}`

#### `compute_effective(type_defaults, mc_overrides)`
- Merges overrides on top of type defaults
- Returns: `{db_path_key: {enable, exist, vlv_w_fb}}`

#### `compare(excel_data, effective, type_defaults, family, mc_idx)`
- For each Excel instrument, looks up effective DB value
- Returns list of comparison rows with match/mismatch flag

#### `write_updated_db(db_text, mc_idx, excel_data, type_defaults, mc_overrides)`
- Keeps all original lines EXCEPT CW.ENABLE/EXIST/VLV_W_FB for the target MachineConfig
- Regenerates CW override lines only where expected ≠ type default
- Writes `SysConfig_Lib_Brew_updated.db`

#### `write_comparison_xlsx(comparison_rows)`
- Writes `InstrumentStatusComparison.xlsx` with columns:
  - **Fixed:** Tag Label, Function, Unit, EM Module (from TAG_MAP; "N/A" if not mapped)
  - **Per family:** Excel Val, Exp EN, Exp EX, Exp VF, DB EN, DB EX, DB VF, Match, Action
- Freeze panes after the 4 fixed columns for easy scrolling

### Tag Path Map (Excel label → DB path)
Hard-coded in `TAG_MAP` dict: `{excel_label: (unit, em, db_field, is_vlv)}`
Updated when new instruments are added to the Excel.

### Configuration Constants
```python
FAMILIES = {
    'BREW 350': {'mc_idx': 7, 'col_idx': 4},   # column D
    'BREW 450': {'mc_idx': 8, 'col_idx': 5},   # column E
}
DB_PATH    = 'SysConfig_Lib_Brew.db'
EXCEL_PATH = 'testBrew.xlsx'
OUT_DB     = 'SysConfig_Lib_Brew_updated.db'
OUT_XLSX   = 'InstrumentStatusComparison.xlsx'
```

### Extensibility
- Add a new family: add a column to Excel + add entry to FAMILIES dict
- New instrument in Excel: add entry to TAG_MAP
- New DB version: just drop in the new `.db` file and re-run
