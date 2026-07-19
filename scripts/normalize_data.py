#!/usr/bin/env python3
"""
Steel Data Normalization Pipeline

Joins manufacturer compositions with objective laboratory measurements
(CATRA TCC edge-retention tests and Charpy impact toughness) into a unified
dataset at data/processed/unified_steels.json, and outputs
data/processed/training_ready.csv for direct model input.

Models are trained on the objective measurements (CATRA, Charpy) plus
first-principles chemistry features. KnifeSteelNerds 1-10 ratings are NOT
used as a training target; they are retained only as an external validation
reference for the corrosion model. The raw source extractions this script
consumes (data/raw/) are maintained privately per the data-use policy; see
DATA_SOURCES.md for full source provenance.
"""

import json
import os
import glob
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# ─── Canonical Name Mapping ───
# Maps variant names → canonical name used in the unified dataset.
# Canonical names match the frontend steel names where possible.
NAME_MAP = {
    # Crucible CPM steels
    "CPM S30V": "CPM S30V", "S30V": "CPM S30V",
    "CPM S35VN": "CPM S35VN", "S35VN": "CPM S35VN",
    "CPM S45VN": "CPM S45VN", "S45VN": "CPM S45VN",
    "CPM S60V": "CPM S60V", "S60V": "CPM S60V",
    "CPM S90V": "CPM S90V", "S90V": "CPM S90V",
    "CPM S110V": "CPM S110V", "S110V": "CPM S110V",
    "CPM S125V": "CPM S125V", "S125V": "CPM S125V",
    "CPM MagnaCut": "CPM MagnaCut", "MagnaCut": "CPM MagnaCut",
    "CPM 3V": "CPM 3V", "3V": "CPM 3V",
    "CPM 4V": "CPM 4V", "4V": "CPM 4V", "V4E/4V": "CPM 4V",
    "CPM 9V": "CPM 9V", "9V": "CPM 9V",
    "CPM 10V": "CPM 10V", "10V": "CPM 10V",
    "CPM 15V": "CPM 15V", "15V": "CPM 15V",
    "CPM 1V": "CPM 1V", "1V": "CPM 1V",
    "CPM 20CV": "CPM 20CV", "20CV": "CPM 20CV",
    "CPM D2": "CPM D2",
    "CPM M4": "CPM M4", "CPM-M4": "CPM M4",
    "CPM 154": "CPM 154", "CPM-154": "CPM 154",
    "154 CM": "154CM", "154CM": "154CM",
    "CPM Rex 45": "CPM Rex 45", "Rex 45": "CPM Rex 45",
    "Rex 45/HAP40": "CPM Rex 45",
    "CPM Rex 76": "CPM Rex 76", "Rex 76": "CPM Rex 76",
    "CPM Rex 121": "CPM Rex 121", "Rex 121": "CPM Rex 121",
    "CPM CruWear": "CPM CruWear", "CPM-CruWear": "CPM CruWear",
    "CruForgeV": "CruForgeV",

    # Three-way equivalence: M390 = 20CV = CTS-204P
    # Use CPM 20CV as canonical for composition, but keep M390 as its own entry
    "M390 Microclean": "M390", "M390": "M390",
    "M390/20CV/204P": "M390",  # KSN groups them
    "204P": "M390",  # Paper 1 name
    "CTS-204P": "CTS-204P",

    # Bohler-Uddeholm
    "M398 Microclean": "M398", "M398": "M398",
    "K390 Microclean": "K390", "K390": "K390",
    "K110 (D2)": "K110",
    "K340 Isodur": "K340",
    "Sverker 21 (D2)": "Sverker 21",
    "Elmax SuperClean": "Elmax", "Elmax": "Elmax",
    "Vanadis 4 Extra SuperClean": "Vanadis 4 Extra",
    "Vanadis 8 SuperClean": "Vanadis 8", "Vanadis 8": "Vanadis 8",
    "Vanadis 10": "Vanadis 10",
    "Sleipner": "Sleipner",
    "Caldie": "Caldie",
    "Rigor": "Rigor",
    "Unimax": "Unimax",
    "Dievar": "Dievar",
    "Corrax": "Corrax",

    # Carpenter
    "CTS-XHP": "CTS-XHP", "XHP": "CTS-XHP",
    "CTS-BD1": "CTS-BD1",
    "CTS-BD1N": "CTS-BD1N", "BD1N": "CTS-BD1N",
    "440C": "440C",

    # Alleima/Sandvik
    "14C28N": "14C28N",
    "12C27": "12C27", "Sandvik-12C27": "12C27",
    "13C26": "13C26",
    "19C27": "19C27",
    "12C27M": "12C27M",

    # Hitachi-Proterial / Takefu
    "ZDP-189": "ZDP-189",
    "VG-10": "VG-10", "VG10": "VG-10",
    "VG-1": "VG-1",
    "VG-2": "VG-2",
    "SG2 (Super Gold 2)": "SG2", "SG2": "SG2", "Super Gold 2": "SG2",
    "Blue Paper Super (Aogami Super)": "Blue Super", "Blue Super": "Blue Super",
    "Blue Paper #1 (Aogami #1)": "Blue #1",
    "Blue Paper #2 (Aogami #2)": "Blue #2",
    "White Paper #1 (Shirogami #1)": "White #1",
    "White Paper #2 (Shirogami #2)": "White #2",
    "Yellow Paper (Kigami)": "Yellow Paper",
    "Silver Steel #3 (Gin-san / Ginsanko)": "Ginsan",
    "AUS-6": "AUS-6",
    "AUS-8": "AUS-8", "AUS-8/8Cr13MoV": "AUS-8",
    "AUS-10": "AUS-10",

    # Missing steels
    "Maxamet": "Maxamet",
    "N690": "N690",
    "CPM-SPY27": "CPM SPY27", "CPM SPY27": "CPM SPY27",
    "3Cr13": "3Cr13",
    "8Cr13MoV": "8Cr13MoV",
    "9Cr18Mo": "9Cr18Mo",
    "7Cr17": "7Cr17",
    "420": "420",
    "5160": "5160",
    "H1": "H1",
    "H2": "H2",
    "W1": "W1",
    "W2": "W2",

    # Standard/academic steels
    "D2": "D2",
    "A2": "A2",
    "O1": "O1",
    "M2": "M2", "M-2": "M2",
    "1095": "1095",
    "1084": "1084",
    "52100": "52100",
    "5160": "5160",
    "8670": "8670",
    "AEB-L": "AEB-L",
    "LC200N": "LC200N",
    "Nitro-V": "Nitro-V",
    "Niolox": "Niolox",
    "Vanax": "Vanax",
    "V-Toku 2": "V-Toku 2", "V-Toku2": "V-Toku 2",
    "26C3": "26C3",
    "80CrV2": "80CrV2",
    "L6": "L6",
    "ApexUltra": "ApexUltra",
    "1.2442": "1.2442",
    "1.2519": "1.2519",
    "1.2562": "1.2562",
    "1.4116": "1.4116",
    "A8 mod": "A8 mod",
    "CD1": "Z-Tuff", "Z-Tuff": "Z-Tuff",
    "Rex 86/Z-Max": "Z-Max", "Z-Max": "Z-Max",
    "420HC": "420HC",
    "440A": "440A",
    "80CrV2": "80CrV2",
    "L6": "L6",
    "ApexUltra": "ApexUltra",
}

# Known compositions for steels that only appear in KSN/Paper 1 (no manufacturer JSON).
# Sources: AISI/ASTM specs, MatWeb, zknives.
KSN_ONLY_COMPOSITIONS = {
    "1095": {"C": 0.95, "Mn": 0.40, "Si": 0.25, "Cr": 0, "V": 0, "Mo": 0, "W": 0},
    "1084": {"C": 0.84, "Mn": 0.75, "Si": 0.25, "Cr": 0, "V": 0, "Mo": 0, "W": 0},
    "52100": {"C": 1.00, "Cr": 1.45, "Mn": 0.35, "Si": 0.25, "Mo": 0, "V": 0, "W": 0},
    "8670": {"C": 0.70, "Cr": 0.50, "Ni": 0.55, "Mo": 0.25, "Mn": 0.85, "Si": 0.25, "V": 0, "W": 0},
    "26C3": {"C": 1.05, "Cr": 0.25, "Mn": 0.35, "Si": 0.25, "Mo": 0, "V": 0, "W": 0},
    "80CrV2": {"C": 0.80, "Cr": 0.50, "V": 0.15, "Mn": 0.40, "Si": 0.30, "Mo": 0, "W": 0},
    "L6": {"C": 0.70, "Cr": 0.75, "Ni": 1.50, "Mo": 0.25, "Mn": 0.60, "Si": 0.25, "V": 0, "W": 0},
    "ApexUltra": {"C": 1.20, "Cr": 14.5, "V": 1.0, "Mo": 1.0, "Mn": 0.40, "Si": 0.40, "W": 0, "Nb": 0},
    "1.4116": {"C": 0.50, "Cr": 14.5, "V": 0.15, "Mo": 0.60, "Mn": 1.0, "Si": 1.0, "W": 0},
    "420HC": {"C": 0.44, "Cr": 13.5, "Mo": 0, "V": 0, "Mn": 0.4, "Si": 0.4, "W": 0},
    "440A": {"C": 0.70, "Cr": 17.0, "Mo": 0.75, "V": 0, "Mn": 1.0, "Si": 1.0, "W": 0},
    "V-Toku 2": {"C": 1.15, "Cr": 0.30, "W": 1.50, "Mn": 0.20, "Si": 0.15, "Mo": 0, "V": 0},
    "CruForgeV": {"C": 0.75, "Cr": 1.0, "V": 0.15, "Mn": 0.50, "Si": 0.25, "Mo": 0, "W": 0},
    "D2": {"C": 1.55, "Cr": 11.5, "V": 0.9, "Mo": 0.8, "Mn": 0.4, "Si": 0.4, "W": 0},
    # Steels with CATRA data missing composition (from AISI/DIN specs, MatWeb, zknives)
    "A2": {"C": 1.00, "Cr": 5.25, "Mo": 1.10, "V": 0.25, "Mn": 0.80, "Si": 0.30, "W": 0},
    "O1": {"C": 0.95, "Cr": 0.50, "V": 0.20, "W": 0.50, "Mn": 1.20, "Si": 0.30, "Mo": 0},
    "M2": {"C": 0.85, "Cr": 4.15, "V": 1.80, "Mo": 5.0, "W": 6.15, "Mn": 0.30, "Si": 0.30, "Co": 0},
    "AEB-L": {"C": 0.67, "Cr": 13.0, "Mn": 0.60, "Si": 0.40, "V": 0, "Mo": 0, "W": 0},
    "LC200N": {"C": 0.50, "Cr": 15.0, "Mo": 0.80, "N": 0.40, "V": 0.10, "Mn": 0.80, "Si": 0.50, "W": 0},
    "Nitro-V": {"C": 0.50, "Cr": 13.0, "N": 0.20, "V": 0.15, "Mn": 0.50, "Si": 0.50, "Mo": 0, "W": 0},
    "CPM CruWear": {"C": 1.10, "Cr": 7.5, "V": 2.4, "Mo": 1.6, "W": 1.15, "Mn": 0.50, "Si": 0.50},
    "CPM S60V": {"C": 2.15, "Cr": 17.0, "V": 5.5, "Mo": 0.40, "Mn": 0.50, "Si": 0.50, "W": 0},
    "Niolox": {"C": 0.80, "Cr": 12.7, "Mo": 1.10, "Nb": 0.70, "V": 0.10, "Mn": 0.40, "Si": 0.50, "W": 0},
    "Vanax": {"C": 0.22, "Cr": 21.2, "N": 1.80, "Mo": 2.60, "V": 1.30, "Mn": 0.50, "Si": 0.50, "W": 0},
    "Z-Max": {"C": 2.30, "Cr": 5.0, "V": 5.0, "Mo": 11.0, "W": 2.0, "Co": 8.0, "Mn": 0.30, "Si": 0.30},
    "Z-Tuff": {"C": 0.20, "Cr": 0, "V": 0, "Mo": 2.0, "W": 0, "Mn": 0.30, "Si": 1.0, "Ni": 3.0, "Co": 8.0},
    "CPM Rex 121": {"C": 3.40, "Cr": 4.0, "V": 9.50, "Mo": 3.75, "W": 10.0, "Co": 5.0, "Mn": 0.30, "Si": 0.30},
    "1.2442": {"C": 1.15, "Cr": 0.70, "V": 0.10, "Mn": 0.35, "Si": 0.25, "Mo": 0, "W": 0},
    "1.2519": {"C": 1.05, "Cr": 1.00, "W": 1.00, "Mn": 0.35, "Si": 0.25, "V": 0, "Mo": 0},
    "1.2562": {"C": 1.00, "Cr": 1.05, "W": 0.60, "Mn": 1.10, "Si": 0.25, "V": 0, "Mo": 0},
    "A8 mod": {"C": 0.55, "Cr": 5.0, "Mo": 1.25, "V": 0.30, "W": 1.25, "Mn": 0.30, "Si": 0.30},
}

# D2 equivalence group (same AISI D2 composition, different brands)
D2_EQUIVALENTS = {"D2", "K110", "Sverker 21", "CPM D2"}

# M390/20CV/204P equivalence group
M390_EQUIVALENTS = {"M390", "CPM 20CV", "CTS-204P"}

COMPOSITION_ELEMENTS = ["C", "Cr", "V", "Mo", "W", "Co", "N", "Mn", "Si", "Nb", "Ni", "S", "P", "Cu", "Al"]
MAJOR_ELEMENTS = ["C", "Cr", "V", "Mo", "W"]

# Known minor element corrections (from cross-validation in the audit)
MINOR_ELEMENT_FIXES = {
    "CPM S30V": {"Mn": 0.5, "Si": 0.5},
    "CPM 20CV": {"Si": 0.7, "Mn": 0.3},
    "VG-10": {"Mn": 0.5, "Si": 0.35},
    "CPM S90V": {"Mn": 0.5, "Si": 0.5},
    "CPM S110V": {"Mn": 0.3, "Si": 0.4},
}


def canonicalize(name: str) -> str:
    """Map a steel name to its canonical form."""
    # Direct lookup
    if name in NAME_MAP:
        return NAME_MAP[name]
    # Try stripping whitespace
    stripped = name.strip()
    if stripped in NAME_MAP:
        return NAME_MAP[stripped]
    # Return as-is if no mapping
    return name


def load_manufacturer_steels():
    """Load all manufacturer steel data from individual JSON files."""
    steels = {}
    sources = [
        ("crucible", RAW_DIR / "crucible"),
        ("bohler-uddeholm", RAW_DIR / "bohler-uddeholm"),
        ("carpenter", RAW_DIR / "carpenter"),
        ("alleima", RAW_DIR / "alleima"),
        ("hitachi-proterial", RAW_DIR / "hitachi-proterial"),
        ("missing-steels", RAW_DIR / "missing-steels"),
    ]

    skip_files = {"_summary.json", "_pocket_book_compositions.json", "_knife_brochure_data.json"}

    for src_name, src_dir in sources:
        if not src_dir.exists():
            continue
        for fpath in sorted(src_dir.glob("*.json")):
            if fpath.name in skip_files:
                continue
            with open(fpath) as f:
                data = json.load(f)

            raw_name = data.get("steel_name", fpath.stem)
            canonical = canonicalize(raw_name)

            comp = data.get("composition", {})
            # Normalize: ensure all standard elements present
            norm_comp = {}
            for elem in COMPOSITION_ELEMENTS:
                val = comp.get(elem, 0)
                norm_comp[elem] = float(val) if val else 0.0

            pm = data.get("powder_metallurgy", False)

            # Extract properties
            toughness = data.get("toughness", {})
            charpy_ftlbs = toughness.get("charpy_ftlbs")
            charpy_joules = toughness.get("charpy_joules")

            wear = data.get("wear_resistance", {})
            catra_pct = wear.get("catra_tcc_pct_vs_baseline")

            corrosion = data.get("corrosion_resistance", {})
            corr_rating = corrosion.get("qualitative_rating")
            pitting_mv = corrosion.get("pitting_potential_mv")

            hardness = data.get("hardness", {})
            typical_hrc = hardness.get("typical_hrc")

            heat_treat = data.get("heat_treatment", {})

            entry = {
                "canonical_name": canonical,
                "raw_names": [raw_name],
                "source": src_name,
                "composition": norm_comp,
                "powder_metallurgy": pm,
                "charpy_ftlbs": charpy_ftlbs,
                "charpy_joules": charpy_joules,
                "catra_tcc_pct_vs_baseline": catra_pct,
                "corrosion_qualitative": corr_rating,
                "pitting_potential_mv": pitting_mv,
                "typical_hrc": typical_hrc,
                "heat_treatment": heat_treat if heat_treat else None,
            }

            # If canonical name already exists, prefer the one with more data
            if canonical in steels:
                existing = steels[canonical]
                existing["raw_names"].append(raw_name)
                # Merge: fill in missing values from new source
                for key in ["charpy_ftlbs", "charpy_joules", "catra_tcc_pct_vs_baseline",
                            "pitting_potential_mv", "typical_hrc"]:
                    if existing[key] is None and entry[key] is not None:
                        existing[key] = entry[key]
                # Prefer composition with more nonzero elements
                existing_nonzero = sum(1 for v in existing["composition"].values() if v > 0)
                new_nonzero = sum(1 for v in norm_comp.values() if v > 0)
                if new_nonzero > existing_nonzero:
                    existing["composition"] = norm_comp
                    existing["source"] = src_name
            else:
                steels[canonical] = entry

    return steels


def load_pocket_book():
    """Load Bohler-Uddeholm Pocket Book composition-only grades."""
    pb_path = RAW_DIR / "bohler-uddeholm" / "_pocket_book_compositions.json"
    if not pb_path.exists():
        return {}

    with open(pb_path) as f:
        grades = json.load(f)

    steels = {}
    for grade in grades:
        raw_name = grade.get("steel_name", "")
        canonical = canonicalize(raw_name)

        # Skip if we already have this steel from individual datasheets
        comp = grade.get("composition", {})
        norm_comp = {}
        for elem in COMPOSITION_ELEMENTS:
            val = comp.get(elem, 0)
            norm_comp[elem] = float(val) if val else 0.0

        steels[canonical] = {
            "canonical_name": canonical,
            "raw_names": [raw_name],
            "source": "bohler-pocket-book",
            "composition": norm_comp,
            "powder_metallurgy": grade.get("powder_metallurgy", False),
            "charpy_ftlbs": None,
            "charpy_joules": None,
            "catra_tcc_pct_vs_baseline": None,
            "corrosion_qualitative": None,
            "pitting_potential_mv": None,
            "typical_hrc": None,
            "heat_treatment": None,
        }

    return steels


def load_paper1_catra():
    """Load Paper 1 CATRA TCC data points."""
    p1_path = RAW_DIR / "academic" / "paper_1.json"
    if not p1_path.exists():
        return {}

    with open(p1_path) as f:
        data = json.load(f)

    # Group by canonical name, keep best TCC (highest HRC closest to 60-62)
    catra_data = {}
    for entry in data.get("steels_tested", []):
        raw_name = entry.get("steel_name", "")
        canonical = canonicalize(raw_name)
        tcc = entry.get("catra_tcc_mm")
        hrc = entry.get("test_hrc")
        other = entry.get("other_properties", {})

        if canonical not in catra_data:
            catra_data[canonical] = []

        catra_data[canonical].append({
            "tcc_mm": tcc,
            "test_hrc": hrc,
            "heat_treatment": other,
        })

    # For each steel, pick the data point closest to HRC 61 (typical knife hardness)
    best = {}
    for canonical, points in catra_data.items():
        if len(points) == 1:
            best[canonical] = points[0]
        else:
            # Pick point closest to 61 HRC
            best[canonical] = min(points, key=lambda p: abs((p["test_hrc"] or 61) - 61))

    return best


def load_ksn_ratings():
    """Load KnifeSteelNerds 1-10 ratings (external validation reference only,
    never used as a training target; raw file kept private)."""
    ksn_path = RAW_DIR / "knifesteelnerds" / "ksn_ratings.json"
    if not ksn_path.exists():
        return {}

    with open(ksn_path) as f:
        ratings = json.load(f)

    result = {}
    for entry in ratings:
        raw_name = entry.get("steel_name", "")
        canonical = canonicalize(raw_name)
        result[canonical] = {
            "toughness": entry.get("toughness"),
            "edge_retention": entry.get("edge_retention"),
            "corrosion_resistance": entry.get("corrosion_resistance"),
            "ease_of_sharpening": entry.get("ease_of_sharpening"),
        }

    return result


def apply_minor_element_fixes(steels):
    """Fill missing minor elements from known cross-references."""
    for canonical, fixes in MINOR_ELEMENT_FIXES.items():
        if canonical in steels:
            comp = steels[canonical]["composition"]
            for elem, val in fixes.items():
                if comp.get(elem, 0) == 0:
                    comp[elem] = val


def compute_derived_features(comp, pm=False):
    """Calculate derived features from composition, including physics-informed ones."""
    c = comp.get("C", 0)
    cr = comp.get("Cr", 0)
    v = comp.get("V", 0)
    mo = comp.get("Mo", 0)
    w = comp.get("W", 0)
    nb = comp.get("Nb", 0)
    n = comp.get("N", 0)
    mn = comp.get("Mn", 0)
    si = comp.get("Si", 0)
    ni = comp.get("Ni", 0)
    co = comp.get("Co", 0)

    total_carbide_formers = v + w + nb + mo
    cr_to_c_ratio = cr / max(c, 0.01)
    is_stainless = 1 if cr >= 13 else 0
    total_alloy = sum(comp.values())
    pren = cr + 3.3 * (mo + 0.5 * w) + 16 * n

    # Physics-informed features

    # Carbide Volume Fraction (approximate Delja-style)
    # Each element contributes to carbide formation proportionally
    cvf = c * 13.5 + cr * 0.18 + v * 1.95 + mo * 0.36 + w * 0.18 + nb * 1.8

    # Excess C above eutectoid (0.77%). Above this, primary carbides form
    # that reduce toughness significantly in non-PM steels
    c_above_eutectoid = max(0, c - 0.77)

    # VC carbide fraction — vanadium carbides (MC type) are the hardest
    # common carbide in tool steels, directly drives wear/edge retention
    vc_fraction = v * 1.95

    # Matrix Cr — Cr remaining in solid solution after carbide formation.
    # Each %C ties up ~4% Cr as M7C3/M23C6. Nb preferentially forms NbC,
    # freeing Cr that would otherwise form Cr-carbides.
    cr_consumed_by_c = max(0, (c - nb * 0.8) * 4.0)
    matrix_cr = max(0, cr - cr_consumed_by_c)

    # Martensite start temperature — lower Ms = more retained austenite = lower toughness
    # Classic formula: Ms = 539 - 423*C_matrix - 30.4*Mn - 17.7*Ni - 12.1*Cr - 7.5*Mo
    c_in_solution = min(c, 0.60)  # only ~0.6% C dissolves at knife HT temps
    ms_temp = 539 - 423 * c_in_solution - 30.4 * mn - 17.7 * ni - 12.1 * cr - 7.5 * mo

    # PM × CVF interaction — powder metallurgy matters most for high-carbide steels
    # PM refines carbide distribution, improving toughness at a given CVF
    pm_flag = 1 if pm else 0
    pm_x_cvf = pm_flag * cvf

    # PM × excess C interaction — PM mitigates the toughness penalty of hypereutectoid C
    pm_x_excess_c = pm_flag * c_above_eutectoid

    return {
        "total_carbide_formers": round(total_carbide_formers, 3),
        "chromium_to_carbon_ratio": round(cr_to_c_ratio, 3),
        "is_stainless": is_stainless,
        "total_alloy_content": round(total_alloy, 3),
        "pren": round(pren, 2),
        "cvf": round(cvf, 3),
        "c_above_eutectoid": round(c_above_eutectoid, 3),
        "vc_fraction": round(vc_fraction, 3),
        "matrix_cr": round(matrix_cr, 3),
        "ms_temp": round(ms_temp, 2),
        "pm_x_cvf": round(pm_x_cvf, 3),
        "pm_x_excess_c": round(pm_x_excess_c, 3),
    }


def build_unified_dataset():
    """Main pipeline: merge all sources into unified dataset."""
    print("Loading manufacturer steels...")
    steels = load_manufacturer_steels()
    print(f"  Loaded {len(steels)} steels from manufacturer datasheets")

    print("Loading Pocket Book compositions...")
    pocket = load_pocket_book()
    # Only add Pocket Book steels that don't already exist
    added = 0
    for canonical, data in pocket.items():
        if canonical not in steels:
            steels[canonical] = data
            added += 1
    print(f"  Added {added} new steels from Pocket Book (skipped {len(pocket) - added} duplicates)")

    print("Applying minor element corrections...")
    apply_minor_element_fixes(steels)

    print("Loading Paper 1 CATRA data...")
    catra = load_paper1_catra()
    print(f"  Loaded CATRA TCC for {len(catra)} steels")

    # Inject known compositions for KSN/Paper-1-only steels
    for canonical, comp_data in KSN_ONLY_COMPOSITIONS.items():
        if canonical not in steels:
            norm_comp = {}
            for elem in COMPOSITION_ELEMENTS:
                norm_comp[elem] = float(comp_data.get(elem, 0))
            steels[canonical] = {
                "canonical_name": canonical,
                "raw_names": [canonical],
                "source": "reference-specs",
                "composition": norm_comp,
                "powder_metallurgy": False,
                "charpy_ftlbs": None,
                "charpy_joules": None,
                "catra_tcc_pct_vs_baseline": None,
                "corrosion_qualitative": None,
                "pitting_potential_mv": None,
                "typical_hrc": None,
                "heat_treatment": None,
            }
    print(f"  Injected {len(KSN_ONLY_COMPOSITIONS)} reference compositions for KSN-only steels")

    print("Loading KSN ratings...")
    ksn = load_ksn_ratings()
    print(f"  Loaded KSN ratings for {len(ksn)} steels")

    # Join CATRA and KSN data into manufacturer records
    catra_joined = 0
    catra_new = 0
    for canonical, cdata in catra.items():
        if canonical in steels:
            steels[canonical]["catra_tcc_mm"] = cdata["tcc_mm"]
            steels[canonical]["catra_test_hrc"] = cdata["test_hrc"]
            catra_joined += 1
        else:
            # Create a minimal record for Paper-1-only steels
            steels[canonical] = {
                "canonical_name": canonical,
                "raw_names": [canonical],
                "source": "academic-paper-1",
                "composition": {elem: 0.0 for elem in COMPOSITION_ELEMENTS},
                "powder_metallurgy": False,
                "charpy_ftlbs": None,
                "charpy_joules": None,
                "catra_tcc_pct_vs_baseline": None,
                "corrosion_qualitative": None,
                "pitting_potential_mv": None,
                "typical_hrc": None,
                "heat_treatment": None,
                "catra_tcc_mm": cdata["tcc_mm"],
                "catra_test_hrc": cdata["test_hrc"],
            }
            catra_new += 1
    print(f"  Joined CATRA TCC: {catra_joined} matched, {catra_new} new (composition-less)")

    ksn_joined = 0
    ksn_unmatched = []
    for canonical, ratings in ksn.items():
        if canonical in steels:
            steels[canonical]["ksn_toughness"] = ratings["toughness"]
            steels[canonical]["ksn_edge_retention"] = ratings["edge_retention"]
            steels[canonical]["ksn_corrosion_resistance"] = ratings["corrosion_resistance"]
            steels[canonical]["ksn_ease_of_sharpening"] = ratings["ease_of_sharpening"]
            ksn_joined += 1
        else:
            ksn_unmatched.append(canonical)
    print(f"  Joined KSN ratings: {ksn_joined} matched, {len(ksn_unmatched)} unmatched")
    if ksn_unmatched:
        print(f"    Unmatched KSN steels: {ksn_unmatched}")

    # Compute derived features for all steels with composition
    for canonical, data in steels.items():
        comp = data["composition"]
        nonzero = sum(1 for v in comp.values() if v > 0)
        if nonzero >= 2:  # At least C + one other
            data["derived_features"] = compute_derived_features(comp, pm=data.get("powder_metallurgy", False))
        else:
            data["derived_features"] = None

    # Ensure all records have consistent fields
    for canonical, data in steels.items():
        data.setdefault("catra_tcc_mm", None)
        data.setdefault("catra_test_hrc", None)

    return steels


def compute_readiness(steels):
    """Assess training readiness for each steel."""
    stats = {
        "total": len(steels),
        "has_composition": 0,
        "has_catra_tcc": 0,
        "has_charpy": 0,
        "has_ksn_validation_ratings": 0,
        "has_composition_and_measurement": 0,
        "training_ready": 0,
    }

    for canonical, data in steels.items():
        comp = data["composition"]
        nonzero = sum(1 for v in comp.values() if v > 0)
        has_comp = nonzero >= 2
        has_tcc = data.get("catra_tcc_mm") is not None
        has_charpy = data.get("charpy_ftlbs") is not None or data.get("charpy_joules") is not None
        has_ksn = data.get("ksn_toughness") is not None

        if has_comp:
            stats["has_composition"] += 1
        if has_tcc:
            stats["has_catra_tcc"] += 1
        if has_charpy:
            stats["has_charpy"] += 1
        if has_ksn:
            stats["has_ksn_validation_ratings"] += 1
        if has_comp and (has_tcc or has_charpy):
            stats["has_composition_and_measurement"] += 1
        # Training readiness = composition + an objective measurement (CATRA/Charpy)
        if has_comp and (has_tcc or has_charpy):
            stats["training_ready"] += 1

    return stats


def write_training_csv(steels):
    """Output a flat CSV suitable for model training."""
    csv_path = PROCESSED_DIR / "training_ready.csv"

    # Only include steels with composition + at least KSN ratings
    rows = []
    for canonical, data in sorted(steels.items()):
        comp = data["composition"]
        nonzero = sum(1 for v in comp.values() if v > 0)
        has_ksn = data.get("ksn_toughness") is not None

        if nonzero < 2:
            continue

        row = {
            "steel_name": canonical,
            "source": data["source"],
            "C": comp.get("C", 0),
            "Cr": comp.get("Cr", 0),
            "V": comp.get("V", 0),
            "Mo": comp.get("Mo", 0),
            "W": comp.get("W", 0),
            "Co": comp.get("Co", 0),
            "N": comp.get("N", 0),
            "Mn": comp.get("Mn", 0),
            "Si": comp.get("Si", 0),
            "Nb": comp.get("Nb", 0),
            "Ni": comp.get("Ni", 0),
            "powder_metallurgy": 1 if data.get("powder_metallurgy") else 0,
        }

        # Derived features
        derived = data.get("derived_features", {}) or {}
        row["total_carbide_formers"] = derived.get("total_carbide_formers", 0)
        row["cr_to_c_ratio"] = derived.get("chromium_to_carbon_ratio", 0)
        row["is_stainless"] = derived.get("is_stainless", 0)
        row["total_alloy_content"] = derived.get("total_alloy_content", 0)
        row["pren"] = derived.get("pren", 0)
        row["cvf"] = derived.get("cvf", 0)
        row["c_above_eutectoid"] = derived.get("c_above_eutectoid", 0)
        row["vc_fraction"] = derived.get("vc_fraction", 0)
        row["matrix_cr"] = derived.get("matrix_cr", 0)
        row["ms_temp"] = derived.get("ms_temp", 0)
        row["pm_x_cvf"] = derived.get("pm_x_cvf", 0)
        row["pm_x_excess_c"] = derived.get("pm_x_excess_c", 0)

        # Measurements
        row["catra_tcc_mm"] = data.get("catra_tcc_mm", "")
        row["catra_test_hrc"] = data.get("catra_test_hrc", "")
        row["charpy_ftlbs"] = data.get("charpy_ftlbs", "")

        rows.append(row)

    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    steels = build_unified_dataset()

    # Write unified JSON
    json_path = PROCESSED_DIR / "unified_steels.json"
    # Convert to list sorted by canonical name
    steel_list = sorted(steels.values(), key=lambda s: s["canonical_name"])
    with open(json_path, "w") as f:
        json.dump(steel_list, f, indent=2)
    print(f"\nWrote {len(steel_list)} steels to {json_path}")

    # Write training CSV
    csv_count = write_training_csv(steels)
    print(f"Wrote {csv_count} steels to {PROCESSED_DIR / 'training_ready.csv'}")

    # Compute and print readiness stats
    stats = compute_readiness(steels)
    print(f"\n{'='*50}")
    print("TRAINING DATA READINESS SUMMARY")
    print(f"{'='*50}")
    print(f"Total unique steels:                  {stats['total']}")
    print(f"With composition (2+ elements):       {stats['has_composition']}")
    print(f"With CATRA TCC measurement:           {stats['has_catra_tcc']}")
    print(f"With Charpy toughness:                {stats['has_charpy']}")
    print(f"With KSN ratings (validation ref):    {stats['has_ksn_validation_ratings']}")
    print(f"Composition + measurement (train-ready): {stats['has_composition_and_measurement']}")

    # Write stats
    stats_path = PROCESSED_DIR / "pipeline_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"\nWrote stats to {stats_path}")


if __name__ == "__main__":
    main()
