"""
compare_cmstat.py
=================
Compare CMStat.db (old format) vs SysConfig_Lib_Brew_updated.db (new format)
against testLBB.xlsx as the reference for expected values.

Old DB (CMStat.db):
  - Instrument field: ("TAG", MASTER_EN, EXIST)  — 3-element tuple
  - MASTER_EN is functionally identical to ENABLE in the new format
  - No per-family (MachineConfig) overrides — all values from TYPE block defaults
  - STAT types: "STAT VALVE", "STAT DI", "STAT MOTOR", "STAT DO", "STAT AI", "STAT AO"

New DB (SysConfig_Lib_Brew_updated.db):
  - CW 16-bit tuple: bit 3 = ENABLE, bit 13 = EXIST, per MachineConfig[N]
  - One set of values per Brew family (BREW 350 = MC[7], etc.)

Output: CMStat_vs_NewDB_Comparison.xlsx
  Fixed cols  : Tag Label | Function | Unit | EM | CMStat MSTR_EN | CMStat EXIST
  Per-family  : Excel Val | Exp EN | Exp EX | NewDB EN | NewDB EX |
                CM vs Exp | NDB vs Exp | CM vs NDB

Reuses from run.py: build_tag_map, parse_excel, parse_type_defaults,
                    parse_mc_overrides, compute_effective, extract_tuple_content,
                    path_key, STAT_TYPES
"""

import re
import json
import sys
import xlsxwriter

from run import (
    build_tag_map,
    parse_excel,
    parse_type_defaults,
    parse_mc_overrides,
    compute_effective,
    extract_tuple_content,
    path_key,
)

# ── Config ────────────────────────────────────────────────────────────────────

CMSTAT_PATH = "CMStat.db"
NEW_DB_PATH = "SysConfig_Lib_Brew_updated.db"
EXCEL_PATH  = "testLBB.xlsx"
OUT_XLSX    = "CMStat_vs_NewDB_Comparison.xlsx"
JOBS_JSON   = "jobs.json"
JOB_NAME    = "Brew"

OLD_STAT_TYPES = {
    "STAT VALVE", "STAT DI", "STAT MOTOR",
    "STAT DO", "STAT AI", "STAT AO",
}


# ── Step 1: Parse CMStat.db TYPE blocks ───────────────────────────────────────

def _parse_old_tuple(content):
    """
    Parse 3-element CMStat tuple content: 'TAG', MASTER_EN, EXIST
    Skips the tag string (first element), returns (master_en: bool, exist: bool).
    () = False,  TRUE/True = True,  FALSE/False = False.
    """
    bools = []
    i = 0
    s = content
    while i < len(s):
        c = s[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "'":                          # string element — skip
            j = s.find("'", i + 1)
            i = (j + 1) if j != -1 else len(s)
        elif c == "(":                          # () = False
            bools.append(False)
            j = s.find(")", i)
            i = (j + 1) if j != -1 else len(s)
        elif c in "TtFf":                       # TRUE or FALSE literal
            j = i
            while j < len(s) and s[j].isalpha():
                j += 1
            bools.append(s[i:j].upper() == "TRUE")
            i = j
        else:
            i += 1
        if len(bools) == 2:
            break

    while len(bools) < 2:
        bools.append(False)
    return bools[0], bools[1]


def parse_cmstat_defaults(db_text):
    """
    Parse TYPE 'EM - XXX' blocks in CMStat.db.
    Returns: {field_name: {'em': str, 'master_en': bool, 'exist': bool}}
    """
    type_pat  = re.compile(r'TYPE\s+"(EM\s*-\s*[^"]+)".*?END_TYPE', re.DOTALL)
    stat_re   = "|".join(re.escape(t) for t in OLD_STAT_TYPES)
    field_pat = re.compile(
        r'(?:"([^"]+)"|([A-Za-z0-9_\-\+\./]+))'
        r'(?:\s*\{[^}]*\})?'
        r'\s*:\s*"(?:' + stat_re + r')"\s*:=\s*',
        re.DOTALL,
    )

    result = {}
    for type_m in type_pat.finditer(db_text):
        em   = type_m.group(1).strip()
        body = type_m.group(0)
        for fm in field_pat.finditer(body):
            field = (fm.group(1) or fm.group(2)).strip()
            p = fm.end()
            while p < len(body) and body[p] in " \t\r\n":
                p += 1
            if p >= len(body) or body[p] != "(":
                continue
            content = extract_tuple_content(body, p)
            master_en, exist = _parse_old_tuple(content)
            result[field] = {"em": em, "master_en": master_en, "exist": exist}
    return result


# ── Step 2: Build comparison rows ─────────────────────────────────────────────

def _excel_display(en, ex):
    """Derive Excel display value (X/O/-) from enable/exist."""
    if en and ex:  return "X"
    if en:         return "O"
    return "-"


def build_cmstat_comparison(excel_data, cmstat_defaults, type_defaults,
                             mc_overrides_all, tag_map, families_cfg):
    """
    One row per instrument across all families.
    CMStat has a single EN/EX value (no per-family variation).
    New DB has per-family EN/EX via MachineConfig overrides.
    """
    # Collect ordered unique tag labels (preserving first-seen order from Excel)
    seen_tags = {}
    for fam_data in excel_data.values():
        for tag_label, info in fam_data.items():
            if tag_label not in seen_tags:
                ti = tag_map.get(tag_label)
                seen_tags[tag_label] = {
                    "function": info.get("function", ""),
                    "unit":     ti[0] if ti else "Unknown",
                    "em":       ti[1] if ti else "Unknown",
                }

    rows = []
    for tag_label, meta in seen_tags.items():
        # Resolve tag name (Excel comment may give a different DB field name)
        # Try resolved_tag from any family that has it
        resolved = tag_label
        for fam_data in excel_data.values():
            inst = fam_data.get(tag_label)
            if inst and inst.get("resolved_tag") and inst["resolved_tag"] != tag_label:
                resolved = inst["resolved_tag"]
                break

        # CMStat effective values — try resolved name first, then label
        cm_info  = cmstat_defaults.get(resolved) or cmstat_defaults.get(tag_label)
        cm_en    = cm_info["master_en"] if cm_info else None   # None = not in CMStat
        cm_ex    = cm_info["exist"]     if cm_info else None

        row = {
            "Tag Label": tag_label,
            "Function":  meta["function"],
            "Unit":      meta["unit"],
            "EM":        meta["em"],
            "CMStat EN": cm_en,
            "CMStat EX": cm_ex,
        }

        for fam_name, mc_idx in families_cfg.items():
            fs   = fam_name.replace(" ", "")
            inst = excel_data.get(fam_name, {}).get(tag_label)

            if inst is None:
                for key in ("ExcelVal", "ExpEN", "ExpEX", "NewDB_EN", "NewDB_EX",
                            "CM_vs_Exp", "NDB_vs_Exp", "CM_vs_NDB"):
                    row[f"{fs}_{key}"] = None
                continue

            exp_en = inst["enable"]
            exp_ex = inst["exist"]
            res    = compute_effective(
                type_defaults, mc_overrides_all.get(mc_idx, {}), resolved, tag_map
            )
            ndb_en, ndb_ex = res[0], res[1]

            xv = _excel_display(exp_en, exp_ex)

            # Match checks
            if cm_en is None:
                cm_exp  = "N/F"   # not found in CMStat
                cm_ndb  = "N/F"
            else:
                cm_exp  = "OK" if (cm_en == exp_en and cm_ex == exp_ex) else "DIFF"
                cm_ndb  = "OK" if (cm_en == ndb_en and cm_ex == ndb_ex) else "DIFF"
            ndb_exp = "OK" if (ndb_en == exp_en and ndb_ex == exp_ex) else "DIFF"

            row[f"{fs}_ExcelVal"]  = xv
            row[f"{fs}_ExpEN"]     = exp_en
            row[f"{fs}_ExpEX"]     = exp_ex
            row[f"{fs}_NewDB_EN"]  = ndb_en
            row[f"{fs}_NewDB_EX"]  = ndb_ex
            row[f"{fs}_CM_vs_Exp"] = cm_exp
            row[f"{fs}_NDB_vs_Exp"]= ndb_exp
            row[f"{fs}_CM_vs_NDB"] = cm_ndb

        rows.append(row)
    return rows


# ── Step 3: Write comparison Excel ────────────────────────────────────────────

def write_cmstat_xlsx(rows, out_path, families_cfg):
    wb = xlsxwriter.Workbook(out_path)
    ws = wb.add_worksheet("CMStat vs NewDB")

    hdr  = wb.add_format({"bold": True, "bg_color": "#003366", "font_color": "white",
                           "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
    ok   = wb.add_format({"bg_color": "#C6EFCE", "border": 1, "align": "center"})
    fail = wb.add_format({"bg_color": "#FFC7CE", "border": 1, "align": "center"})
    warn = wb.add_format({"bg_color": "#FFEB9C", "border": 1, "align": "center"})
    norm = wb.add_format({"border": 1})
    titl = wb.add_format({"bold": True, "font_size": 14, "bg_color": "#1F4E79",
                           "font_color": "white", "align": "center", "valign": "vcenter"})
    subh = wb.add_format({"bold": True, "bg_color": "#2E75B6", "font_color": "white",
                           "border": 1, "align": "center"})
    cm_t = wb.add_format({"bg_color": "#C6EFCE", "border": 1, "align": "center"})   # CMStat T
    cm_f = wb.add_format({"bg_color": "#F2F2F2", "border": 1, "align": "center"})   # CMStat F

    fam_names    = list(families_cfg.keys())
    COLS_PER_FAM = 8    # ExcelVal | ExpEN | ExpEX | NewDB EN | NewDB EX | CM vs Exp | NDB vs Exp | CM vs NDB
    FIXED        = 6    # Tag Label | Function | Unit | EM | CMStat MSTR_EN | CMStat EXIST
    total_cols   = FIXED + len(fam_names) * COLS_PER_FAM

    # Row 0: title banner
    ws.merge_range(0, 0, 0, total_cols - 1,
        "CMStat.db (MASTER_EN) vs SysConfig_Lib_Brew_updated.db (ENABLE/EXIST) — ref: testLBB.xlsx",
        titl)
    ws.set_row(0, 30)

    # Row 1: family group headers
    for c in range(FIXED):
        ws.write(1, c, "", hdr)
    col = FIXED
    for fn in fam_names:
        ws.merge_range(1, col, 1, col + COLS_PER_FAM - 1, fn, subh)
        col += COLS_PER_FAM
    ws.set_row(1, 25)

    # Row 2: sub-column headers
    fixed_hdrs  = ["Tag Label", "Function", "Unit", "EM", "CMStat\nMSTR_EN", "CMStat\nEXIST"]
    fixed_widths = [18, 32, 14, 14, 11, 11]
    for c, (h, w) in enumerate(zip(fixed_hdrs, fixed_widths)):
        ws.write(2, c, h, hdr)
        ws.set_column(c, c, w)

    sub_cols   = ["Excel\nVal", "Exp\nEN", "Exp\nEX", "NewDB\nEN", "NewDB\nEX",
                  "CM\nvs Exp", "NDB\nvs Exp", "CM\nvs NDB"]
    sub_widths = [8, 7, 7, 8, 8, 10, 10, 10]
    col = FIXED
    for _ in fam_names:
        for h, w in zip(sub_cols, sub_widths):
            ws.write(2, col, h, hdr)
            ws.set_column(col, col, w)
            col += 1
    ws.set_row(2, 40)
    ws.freeze_panes(3, FIXED)

    def b(v):
        if v is None:       return "N/F"
        return ("T" if v else "F") if isinstance(v, bool) else str(v)

    def mfmt(v):
        if v == "OK":   return ok
        if v == "DIFF": return fail
        if v == "N/F":  return warn
        return norm

    for ri, rec in enumerate(rows, start=3):
        ws.write(ri, 0, rec["Tag Label"], norm)
        ws.write(ri, 1, rec["Function"],  norm)
        ws.write(ri, 2, rec["Unit"],      norm)
        ws.write(ri, 3, rec["EM"],        norm)
        cm_en = rec["CMStat EN"]
        cm_ex = rec["CMStat EX"]
        ws.write(ri, 4, b(cm_en), cm_t if cm_en else (cm_f if cm_en is False else warn))
        ws.write(ri, 5, b(cm_ex), cm_t if cm_ex else (cm_f if cm_ex is False else warn))

        col = FIXED
        for fn in fam_names:
            fs  = fn.replace(" ", "")
            xv  = rec.get(f"{fs}_ExcelVal")
            e_en = rec.get(f"{fs}_ExpEN")
            e_ex = rec.get(f"{fs}_ExpEX")
            d_en = rec.get(f"{fs}_NewDB_EN")
            d_ex = rec.get(f"{fs}_NewDB_EX")
            cv  = rec.get(f"{fs}_CM_vs_Exp",  "-")
            nv  = rec.get(f"{fs}_NDB_vs_Exp", "-")
            cnv = rec.get(f"{fs}_CM_vs_NDB",  "-")

            if xv is None:
                for _ in range(COLS_PER_FAM):
                    ws.write(ri, col, "-", norm); col += 1
                continue

            xfmt = ok if xv == "X" else (warn if xv == "O" else norm)
            ws.write(ri, col, xv,      xfmt);                         col += 1
            ws.write(ri, col, b(e_en), ok if e_en else norm);         col += 1
            ws.write(ri, col, b(e_ex), ok if e_ex else norm);         col += 1
            ws.write(ri, col, b(d_en), ok if d_en else norm);         col += 1
            ws.write(ri, col, b(d_ex), ok if d_ex else norm);         col += 1
            ws.write(ri, col, cv  if cv  else "-", mfmt(cv));         col += 1
            ws.write(ri, col, nv  if nv  else "-", mfmt(nv));         col += 1
            ws.write(ri, col, cnv if cnv else "-", mfmt(cnv));        col += 1

    wb.close()
    print(f"  Written: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Load Brew families config from jobs.json
    with open(JOBS_JSON) as f:
        config = json.load(f)
    job = next((j for j in config["jobs"] if j["name"] == JOB_NAME), None)
    if not job:
        print(f'ERROR: job "{JOB_NAME}" not found in {JOBS_JSON}')
        sys.exit(1)
    families_cfg = job["families"]

    print(f"[1] Reading {CMSTAT_PATH}...")
    cmstat_text = open(CMSTAT_PATH, encoding="utf-8-sig").read()

    print(f"[2] Reading {NEW_DB_PATH}...")
    new_db_text = open(NEW_DB_PATH, encoding="utf-8-sig").read()

    print("[3] Building tag map from new DB...")
    tag_map = build_tag_map(new_db_text)
    print(f"    {len(tag_map)} instruments discovered")

    print(f"[4] Parsing Excel reference: {EXCEL_PATH}...")
    excel_data = parse_excel(EXCEL_PATH, families_cfg, tag_map)
    for fam, data in excel_data.items():
        print(f"    {fam}: {len(data)} instruments")

    print("[5] Parsing CMStat.db defaults (MASTER_EN / EXIST)...")
    cmstat_defaults = parse_cmstat_defaults(cmstat_text)
    print(f"    {len(cmstat_defaults)} instruments found in CMStat.db")

    print("[6] Parsing new DB type defaults...")
    type_defaults = parse_type_defaults(new_db_text, tag_map)
    print(f"    {len(type_defaults)} defaults parsed")

    print("[7] Parsing new DB MC overrides per family...")
    mc_overrides_all = {}
    for fam_name, mc_idx in families_cfg.items():
        mc_overrides_all[mc_idx] = parse_mc_overrides(new_db_text, mc_idx)
        print(f"    MC[{mc_idx}] ({fam_name}): {len(mc_overrides_all[mc_idx])} CW overrides")

    print("[8] Building comparison rows...")
    rows = build_cmstat_comparison(
        excel_data, cmstat_defaults, type_defaults,
        mc_overrides_all, tag_map, families_cfg,
    )
    print(f"    {len(rows)} instruments compared")

    # Summary
    in_cmstat = sum(1 for r in rows if r["CMStat EN"] is not None)
    print(f"\n    Instruments found in CMStat.db : {in_cmstat}")
    print(f"    Instruments NOT in CMStat.db  : {len(rows) - in_cmstat}")

    print(f"\n[9] Writing: {OUT_XLSX}")
    write_cmstat_xlsx(rows, OUT_XLSX, families_cfg)

    print("\nDONE.")
    print(f"  Report: {OUT_XLSX}")


if __name__ == "__main__":
    main()
