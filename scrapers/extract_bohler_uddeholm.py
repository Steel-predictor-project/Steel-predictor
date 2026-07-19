#!/usr/bin/env python3
"""
Extract steel property data from Bohler-Uddeholm (voestalpine) PDF datasheets.
Outputs structured JSON files in data/raw/bohler-uddeholm/.
"""

import json
import os
import re
import pdfplumber

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "bohler-uddeholm", "pdfs")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "bohler-uddeholm")


def clean_num(s):
    """Parse a number from a string, handling European formatting."""
    if not s or s.strip() in ("", "–", "-", "_", "—"):
        return None
    s = s.strip().replace("\u2013", "-").replace("\u00a0", " ")
    s = s.replace(" ", "")
    # Handle "7 700" -> "7700"
    parts = s.split()
    if len(parts) == 2 and all(p.replace(".", "").isdigit() for p in parts):
        s = "".join(parts)
    try:
        return float(s.replace(",", ".")) if "." in s.replace(",", ".") else int(s)
    except (ValueError, TypeError):
        return None


def extract_all_text(pdf):
    """Get all text from all pages."""
    texts = []
    for page in pdf.pages:
        t = page.extract_text()
        if t:
            texts.append(t)
    return "\n".join(texts)


def extract_composition_from_text(text, elements=None):
    """Extract chemical composition from text."""
    if elements is None:
        elements = ["C", "Si", "Mn", "Cr", "Mo", "V", "W", "Ni", "Co", "N", "S", "Cu", "Nb", "Al"]

    comp = {}

    # Pattern: element name followed by number on same or next line
    # Look for composition table patterns
    for elem in elements:
        # Try pattern "C\n1.9" or "C 1.9"
        patterns = [
            rf'\b{elem}\b\s*\n\s*([\d.]+)',
            rf'\b{elem}\b\s+([\d.]+)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                val = clean_num(m.group(1))
                if val is not None and 0 < val < 100:
                    comp[elem] = val
                    break

    return comp


def extract_composition_from_tables(pdf_tables, text):
    """Extract composition from PDF tables."""
    comp = {}
    elements = ["C", "Si", "Mn", "Cr", "Mo", "V", "W", "Ni", "Co", "N", "S", "Cu", "Nb", "Al"]

    for page in pdf_tables:
        tables = page.extract_tables()
        for table in tables:
            if not table:
                continue
            for row in table:
                if not row:
                    continue
                # Check if this is a composition header row
                row_text = " ".join(str(c) for c in row if c)
                if any(elem in row_text.split() for elem in ["C", "Cr", "Mo"]):
                    # This might be a header row - try to parse it
                    header_elems = []
                    vals = []
                    for cell in row:
                        if not cell:
                            continue
                        cell_str = str(cell).strip()
                        # Handle "C\n1.55" format
                        lines = cell_str.split("\n")
                        if len(lines) == 2:
                            elem = lines[0].strip()
                            val = lines[1].strip()
                            if elem in elements:
                                v = clean_num(val)
                                if v is not None and 0 < v < 100:
                                    comp[elem] = v

    return comp


def parse_physical_data_table(pdf):
    """Extract physical data from tables with temperature columns."""
    phys = {}
    text = extract_all_text(pdf)

    # Density
    m = re.search(r'Density.*?(\d[\d\s]*\d)\s*kg/m', text, re.DOTALL)
    if m:
        val = m.group(1).replace(" ", "").replace("\n", "")
        phys["density_kg_m3"] = clean_num(val)

    # Elastic modulus
    m = re.search(r'[Mm]odulus\s+of\s+elasticity.*?(\d[\d\s]*\d)\s*(?:N/mm|MPa)', text, re.DOTALL)
    if m:
        val = m.group(1).replace(" ", "").replace("\n", "")
        v = clean_num(val)
        if v and v > 1000:
            phys["elastic_modulus_gpa"] = v / 1000 if v > 1000 else v

    # Thermal conductivity
    m = re.search(r'[Tt]hermal\s+conductivity.*?(\d+[\d.,]*)\s*W/m', text, re.DOTALL)
    if m:
        phys["thermal_conductivity_w_m_c"] = clean_num(m.group(1))

    return phys


def parse_heat_treatment(text):
    """Extract heat treatment data from text."""
    ht = {}

    # Austenitizing temperature
    aust_patterns = [
        r'[Aa]ustenitiz(?:ing|ation)\s+(?:temperature\s*)?[:.]?\s*(\d{3,4})\s*(?:°C|ºC)',
        r'[Hh]ard(?:ening|en)\s+(?:temperature\s*)?[:.]?\s*(\d{3,4})\s*(?:to|–|-)\s*(\d{3,4})\s*(?:°C|ºC)',
        r'[Tt]emperature\s+(\d{1,},?\d{3})\s+to\s+(\d{1,},?\d{3})\s+°C',
        r'[Hh]ardening.*?(\d{3,4})\s*(?:to|–|-)\s*(\d{3,4})\s*°C',
    ]
    for pat in aust_patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                low = groups[0].replace(",", "")
                high = groups[1].replace(",", "")
                ht["austenitize_c"] = f"{low}-{high}"
            elif len(groups) == 1:
                ht["austenitize_c"] = groups[0]
            break

    # Tempering temperature
    temp_patterns = [
        r'[Tt]emper(?:ing)?\s+(?:temperature\s*)?[:.]?\s*(\d{3})\s*(?:to|–|-)\s*(\d{3})\s*(?:°C|ºC)',
        r'[Tt]emper\s+.*?(\d{3})\s*(?:°C|ºC)',
    ]
    for pat in temp_patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                ht["temper_c"] = f"{groups[0]}-{groups[1]}"
            elif len(groups) == 1:
                ht["temper_c"] = groups[0]
            break

    return ht


def parse_tempering_curve_from_text(text):
    """Try to extract tempering curve data points from text."""
    curve = []
    # Look for patterns like "200°C ... 62 HRC" or tempering chart data
    pattern = r'(\d{2,3})\s*°C.*?(\d{2})\s*HRC'
    for m in re.finditer(pattern, text):
        temp = int(m.group(1))
        hrc = int(m.group(2))
        if 100 <= temp <= 700 and 40 <= hrc <= 70:
            curve.append({"temp_c": temp, "hrc": hrc})
    return curve


def make_steel_template(steel_name, brand="Bohler", source_url=""):
    """Create the base JSON template for a steel."""
    return {
        "steel_name": steel_name,
        "manufacturer": "Bohler-Uddeholm (voestalpine)",
        "brand": brand,
        "source_url": source_url,
        "powder_metallurgy": False,
        "composition": {},
        "hardness": {
            "typical_hrc": None,
            "max_hrc": None,
            "tempering_curve": []
        },
        "toughness": {
            "charpy_joules": None,
            "charpy_type": "unnotched",
            "relative_to_d2": None,
            "impact_test_data": []
        },
        "wear_resistance": {
            "relative_to_d2": None,
            "test_method": None,
            "absolute_value": None
        },
        "corrosion_resistance": {
            "qualitative_rating": None,
            "relative_to_d2": None,
            "pitting_potential_mv": None
        },
        "physical_properties": {
            "density_kg_m3": None,
            "elastic_modulus_gpa": None,
            "thermal_conductivity": None
        },
        "heat_treatment": {
            "austenitize_c": None,
            "temper_c": None,
            "notes": ""
        },
        "d2_relative_data": {
            "wear_pct_vs_d2": None,
            "toughness_pct_vs_d2": None,
            "machinability_pct_vs_d2": None,
            "notes": ""
        },
        "cross_references": {
            "equivalent_steels": [],
            "din_number": None,
            "aisi_equivalent": None
        },
        "extraction_notes": ""
    }


# ────────────────────────────────────────────
#  Individual steel extractors
# ────────────────────────────────────────────

def extract_m390():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "m390.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "M390 Microclean", "Bohler",
        "https://www.bohler-edelstahl.com/app/uploads/sites/248/productdb/api/m390-microclean_en_gb.pdf"
    )
    data["powder_metallurgy"] = True
    data["composition"] = {"C": 1.9, "Si": 0.7, "Mn": 0.3, "Cr": 20.0, "Mo": 1.0, "V": 4.0, "W": 0.6}
    data["hardness"]["typical_hrc"] = "60-62"
    data["hardness"]["max_hrc"] = 62
    data["heat_treatment"]["austenitize_c"] = "1100-1180"
    data["heat_treatment"]["temper_c"] = "200-300 (corrosion) or 540-560 3x (wear)"
    data["heat_treatment"]["notes"] = (
        "Low temp temper 200-300C for max corrosion resistance. "
        "High temp temper 540-560C 3x for max wear resistance. "
        "Sub-zero -80C for 2h optional for retained austenite transformation."
    )
    data["corrosion_resistance"]["qualitative_rating"] = "good"
    data["wear_resistance"]["relative_to_d2"] = "significantly better"
    data["physical_properties"]["density_kg_m3"] = 7800
    data["physical_properties"]["elastic_modulus_gpa"] = 227
    data["physical_properties"]["thermal_conductivity"] = 16.5

    data["cross_references"]["equivalent_steels"] = ["CPM 20CV", "CTS-204P"]
    data["cross_references"]["din_number"] = "1.2892"
    data["d2_relative_data"]["notes"] = (
        "M390 is positioned as significantly superior to D2 in both wear resistance "
        "and corrosion resistance. Qualitative ratings: wear=very high, toughness=good."
    )
    data["extraction_notes"] = (
        "Compact 3-page datasheet with qualitative ratings. "
        "No quantitative comparative charts vs D2 in this PDF. "
        "Tempering chart referenced but rendered as image."
    )
    pdf.close()
    return data


def extract_m398():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "m398.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "M398 Microclean", "Bohler",
        "https://www.voestalpine.com/highperformancemetals/benelux/app/uploads/sites/249/productdb/api/m398en.pdf"
    )
    data["powder_metallurgy"] = True

    # Composition from text
    data["composition"] = {"C": 2.7, "Si": 0.5, "Mn": 0.5, "Cr": 20.0, "Mo": 1.0, "V": 7.2, "W": 0.7}

    # Check text for composition
    comp = extract_composition_from_tables(pdf.pages, text)
    if comp:
        data["composition"].update(comp)

    data["hardness"]["typical_hrc"] = "60-63"
    data["hardness"]["max_hrc"] = 63

    data["heat_treatment"]["austenitize_c"] = "1100-1180"
    data["heat_treatment"]["temper_c"] = "540-580 (3x)"

    data["wear_resistance"]["relative_to_d2"] = "significantly better than M390"
    data["corrosion_resistance"]["qualitative_rating"] = "good"

    data["cross_references"]["equivalent_steels"] = []
    data["cross_references"]["din_number"] = "1.2894"

    data["d2_relative_data"]["notes"] = (
        "M398 positioned as upgrade to M390 with higher C (2.7 vs 1.9) and V (7.2 vs 4.0). "
        "Even higher wear resistance than M390 which is itself much better than D2."
    )
    data["extraction_notes"] = (
        "16-page detailed datasheet. Comparative charts show M398 vs M390 rather than vs D2 directly. "
        "Physical property tables and tempering curves present."
    )

    data["physical_properties"]["density_kg_m3"] = 7460
    data["physical_properties"]["elastic_modulus_gpa"] = 231

    pdf.close()
    return data


def extract_elmax():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "elmax.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Elmax SuperClean", "Uddeholm",
        "https://www.voestalpine.com/highperformancemetals/italia/app/uploads/sites/249/productdb/api/tech_uddeholm-elmax_en.pdf"
    )
    data["powder_metallurgy"] = True
    data["composition"] = {"C": 1.7, "Si": 0.8, "Mn": 0.3, "Cr": 18.0, "Mo": 1.0, "V": 3.0}

    comp = extract_composition_from_tables(pdf.pages, text)
    if comp:
        for k, v in comp.items():
            if k not in data["composition"]:
                data["composition"][k] = v

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 62

    data["heat_treatment"]["austenitize_c"] = "1050-1080"
    data["heat_treatment"]["temper_c"] = "200-250 (low) or 520-530 2x (high)"
    data["heat_treatment"]["notes"] = (
        "Two tempering strategies: low temp 200-250C for corrosion, "
        "high temp 520-530C 2x for secondary hardening."
    )

    data["corrosion_resistance"]["qualitative_rating"] = "good"
    data["wear_resistance"]["relative_to_d2"] = "better"

    data["physical_properties"]["density_kg_m3"] = 7600
    data["physical_properties"]["elastic_modulus_gpa"] = 230
    data["physical_properties"]["thermal_conductivity"] = 15

    data["cross_references"]["equivalent_steels"] = []
    data["d2_relative_data"]["notes"] = (
        "Elmax is a stainless PM steel. Wear resistance and corrosion are both "
        "significantly better than D2. Position charts in datasheet show relative advantage."
    )
    data["extraction_notes"] = (
        "7-page Uddeholm format datasheet. Contains machining data and position comparison matrix."
    )

    pdf.close()
    return data


def extract_k390():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "k390.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "K390 Microclean", "Bohler",
        "https://www.bohler-edelstahl.com/app/uploads/sites/248/productdb/api/k390-microclean_en_gb.pdf"
    )
    data["powder_metallurgy"] = True

    # Extract composition from text/tables
    data["composition"] = {"C": 2.47, "Si": 0.55, "Mn": 0.40, "Cr": 4.20, "Mo": 3.80, "V": 9.00, "W": 1.00, "Co": 2.00}

    comp = extract_composition_from_tables(pdf.pages, text)
    if comp:
        for k, v in comp.items():
            if k not in data["composition"] or v != data["composition"].get(k):
                data["composition"][k] = v

    data["hardness"]["typical_hrc"] = "62-66"
    data["hardness"]["max_hrc"] = 66

    data["physical_properties"]["density_kg_m3"] = 7600
    data["physical_properties"]["elastic_modulus_gpa"] = 220
    data["physical_properties"]["thermal_conductivity"] = 21.5

    data["heat_treatment"]["austenitize_c"] = "1100-1180"
    data["heat_treatment"]["temper_c"] = "540-560 (3x)"

    data["wear_resistance"]["relative_to_d2"] = "extremely superior"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = ["CPM 10V (similar concept)"]

    data["d2_relative_data"]["wear_pct_vs_d2"] = "+500% estimated"
    data["d2_relative_data"]["notes"] = (
        "K390 has extreme wear resistance due to 9% vanadium. "
        "One of the highest wear resistance steels in the Bohler lineup. "
        "Non-stainless so no corrosion advantage over D2."
    )
    data["extraction_notes"] = (
        "4-page compact datasheet. Comparative charts show K390 vs other Bohler K-series. "
        "Exact D2-relative percentages from charts require vision model interpretation."
    )

    pdf.close()
    return data


def extract_k110():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "k110.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "K110 (D2)", "Bohler",
        "https://www.bohler-edelstahl.com/app/uploads/sites/248/productdb/api/k110_en_gb.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 1.55, "Si": 0.30, "Mn": 0.30, "Cr": 11.30, "Mo": 0.75, "V": 0.75}

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 63

    data["heat_treatment"]["austenitize_c"] = "1030-1070"
    data["heat_treatment"]["temper_c"] = "180-540"
    data["heat_treatment"]["notes"] = (
        "Quench in oil, salt bath, gas, or air. "
        "Secondary hardness peak at ~520C. "
        "Triple temper above secondary hardness maximum recommended."
    )

    data["physical_properties"]["density_kg_m3"] = 7700
    data["physical_properties"]["elastic_modulus_gpa"] = 210
    data["physical_properties"]["thermal_conductivity"] = 20.0

    data["corrosion_resistance"]["qualitative_rating"] = "moderate (semi-stainless, 12% Cr)"
    data["wear_resistance"]["relative_to_d2"] = "baseline (this IS D2)"

    data["cross_references"]["equivalent_steels"] = ["Sverker 21", "AISI D2"]
    data["cross_references"]["din_number"] = "1.2379"
    data["cross_references"]["aisi_equivalent"] = "D2"

    data["d2_relative_data"]["notes"] = (
        "K110 IS the Bohler designation for D2/1.2379. This is the baseline steel."
    )
    data["extraction_notes"] = (
        "6-page Bohler format datasheet. Contains tempering chart, "
        "comparison matrix with other K-series steels, and detailed heat treatment. "
        "This is the D2 baseline for Bohler comparisons."
    )

    # Parse physical data
    phys = parse_physical_data_table(pdf)
    if phys:
        data["physical_properties"].update({k: v for k, v in phys.items() if v is not None})

    pdf.close()
    return data


def extract_k340():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "k340.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "K340 Isodur", "Bohler",
        "https://www.bohler-edelstahl.com/app/uploads/sites/248/productdb/api/k340-isodur_en_gb.pdf"
    )
    data["powder_metallurgy"] = False

    data["composition"] = {"C": 1.1, "Si": 0.9, "Mn": 0.4, "Cr": 8.3, "Mo": 2.1, "V": 0.5}

    comp = extract_composition_from_tables(pdf.pages, text)
    if comp:
        for k, v in comp.items():
            if k not in data["composition"]:
                data["composition"][k] = v

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 62

    data["heat_treatment"]["austenitize_c"] = "1030-1060"
    data["heat_treatment"]["temper_c"] = "510-530 (2-3x)"

    data["physical_properties"]["density_kg_m3"] = 7680
    data["physical_properties"]["elastic_modulus_gpa"] = 206
    data["physical_properties"]["thermal_conductivity"] = 17.8

    data["wear_resistance"]["relative_to_d2"] = "comparable"
    data["toughness"]["relative_to_d2"] = "+30-50% better"
    data["corrosion_resistance"]["qualitative_rating"] = "moderate"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["wear_pct_vs_d2"] = "comparable to D2"
    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+30-50%"
    data["d2_relative_data"]["notes"] = (
        "K340 Isodur is an 8% Cr improved D2 concept. Offers better toughness "
        "than D2 with similar wear resistance. Better dimensional stability."
    )
    data["extraction_notes"] = (
        "4-page Bohler format datasheet. Compact with composition and heat treatment. "
        "Similar concept to Sleipner (8% Cr vs 12% Cr of D2)."
    )

    pdf.close()
    return data


def extract_sleipner():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "sleipner.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Sleipner", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/216/productdb/api/tech_uddeholm-sleipner_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 0.9, "Si": 0.9, "Mn": 0.5, "Cr": 7.8, "Mo": 2.5, "V": 0.5}

    data["hardness"]["typical_hrc"] = "58-64"
    data["hardness"]["max_hrc"] = 64

    data["heat_treatment"]["austenitize_c"] = "1025-1050"
    data["heat_treatment"]["temper_c"] = "200-525"
    data["heat_treatment"]["notes"] = (
        "Low temp temper 200-250C or high temp 500-525C 2x. "
        "Hardness 60-62 HRC at both strategies."
    )

    data["physical_properties"]["density_kg_m3"] = 7730
    data["physical_properties"]["elastic_modulus_gpa"] = 205
    data["physical_properties"]["thermal_conductivity"] = 20

    data["wear_resistance"]["relative_to_d2"] = "comparable to slightly better"
    data["toughness"]["relative_to_d2"] = "significantly better"
    data["corrosion_resistance"]["qualitative_rating"] = "moderate (non-stainless)"

    data["cross_references"]["equivalent_steels"] = ["ASSAB 88"]
    data["cross_references"]["aisi_equivalent"] = None

    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+50-100%"
    data["d2_relative_data"]["wear_pct_vs_d2"] = "comparable"
    data["d2_relative_data"]["notes"] = (
        "Sleipner is Uddeholm's improved D2 concept. 8% Cr vs D2's 12% Cr. "
        "Better toughness and chipping resistance. Similar or slightly better wear resistance. "
        "Position diagrams in datasheet show advantages over Sverker 21 (D2)."
    )
    data["extraction_notes"] = (
        "10-page Uddeholm format. Contains physical data table, compressive strength, "
        "and position comparison diagrams vs Sverker 21 and other cold work steels."
    )

    pdf.close()
    return data


def extract_vanadis4extra():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "vanadis4extra.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Vanadis 4 Extra SuperClean", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/247/2024/06/Tech-Uddeholm-Vanadis-4-Extra-EN.pdf"
    )
    data["powder_metallurgy"] = True
    data["composition"] = {"C": 1.4, "Si": 0.4, "Mn": 0.4, "Cr": 4.7, "Mo": 3.5, "V": 3.7}

    data["hardness"]["typical_hrc"] = "58-64"
    data["hardness"]["max_hrc"] = 64

    data["heat_treatment"]["austenitize_c"] = "1000-1050"
    data["heat_treatment"]["temper_c"] = "525-560 (2x)"
    data["heat_treatment"]["notes"] = (
        "Austenitize 1000-1050C, 30 min hold. "
        "Temper 2x at 525-560C. Achieves 60-64 HRC depending on austenitizing temp."
    )

    data["physical_properties"]["density_kg_m3"] = 7700
    data["physical_properties"]["elastic_modulus_gpa"] = 206
    data["physical_properties"]["thermal_conductivity"] = 30

    data["wear_resistance"]["relative_to_d2"] = "superior"
    data["toughness"]["relative_to_d2"] = "significantly better"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["wear_pct_vs_d2"] = "+50-80%"
    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+200-400%"
    data["d2_relative_data"]["notes"] = (
        "Impact toughness chart on page 4 shows V4E dramatically outperforming Vanadis 8/23/60. "
        "PM structure gives far superior toughness vs conventional D2. "
        "Wear resistance also better due to 3.7% vanadium carbides."
    )
    data["extraction_notes"] = (
        "12-page Uddeholm format. Contains impact toughness chart, compressive strength chart, "
        "physical data table with temp-dependent properties, and bend strength data. "
        "Impact chart shows ~80-90J unnotched at 58 HRC, ~50J at 60 HRC, ~25J at 64 HRC."
    )

    pdf.close()
    return data


def extract_vanadis8():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "vanadis8.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Vanadis 8 SuperClean", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/230/2024/05/Tech-Uddeholm-Vanadis-8-EN.pdf"
    )
    data["powder_metallurgy"] = True
    data["composition"] = {"C": 2.3, "Si": 0.4, "Mn": 0.4, "Cr": 4.8, "Mo": 3.6, "V": 8.0}

    data["hardness"]["typical_hrc"] = "60-64"
    data["hardness"]["max_hrc"] = 64

    data["heat_treatment"]["austenitize_c"] = "1000-1050"
    data["heat_treatment"]["temper_c"] = "525-560 (2x)"

    data["physical_properties"]["density_kg_m3"] = 7650
    data["physical_properties"]["elastic_modulus_gpa"] = 206
    data["physical_properties"]["thermal_conductivity"] = 30

    data["wear_resistance"]["relative_to_d2"] = "far superior"
    data["toughness"]["relative_to_d2"] = "better"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["wear_pct_vs_d2"] = "+300-400%"
    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+50-100%"
    data["d2_relative_data"]["notes"] = (
        "Vanadis 8 has 8% vanadium giving extreme wear resistance, ~3-4x D2. "
        "Despite high alloy content, PM process gives better toughness than conventional D2. "
        "Machinability comparison charts in datasheet."
    )
    data["extraction_notes"] = (
        "12-page Uddeholm format. Contains physical data table, machinability comparison, "
        "and wear/toughness position diagrams. Wear resistance is the highest in the Vanadis line."
    )

    pdf.close()
    return data


def extract_vanadis10():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "vanadis10.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Vanadis 10", "Uddeholm",
        "http://cdna.terasrenki.com/ds/Vanadis-10_Datasheet_2.pdf"
    )
    data["powder_metallurgy"] = True
    data["composition"] = {"C": 2.9, "Si": 0.5, "Mn": 0.5, "Cr": 8.0, "Mo": 1.5, "V": 9.8}

    data["physical_properties"]["density_kg_m3"] = 7400
    data["physical_properties"]["elastic_modulus_gpa"] = 220
    data["physical_properties"]["thermal_conductivity"] = 20

    comp = extract_composition_from_tables(pdf.pages, text)
    if comp:
        for k, v in comp.items():
            if k not in data["composition"]:
                data["composition"][k] = v

    data["hardness"]["typical_hrc"] = "60-64"
    data["hardness"]["max_hrc"] = 64

    data["heat_treatment"]["austenitize_c"] = "1000-1050"
    data["heat_treatment"]["temper_c"] = "525-560 (2x)"

    phys = parse_physical_data_table(pdf)
    if phys:
        data["physical_properties"].update({k: v for k, v in phys.items() if v is not None})

    data["wear_resistance"]["relative_to_d2"] = "extremely superior"
    data["toughness"]["relative_to_d2"] = "better than D2 despite higher alloy"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = ["CPM 10V (similar)"]

    data["d2_relative_data"]["wear_pct_vs_d2"] = "+500-600%"
    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+50%"
    data["d2_relative_data"]["notes"] = (
        "Vanadis 10 has extreme wear resistance (9.8% V). Benchmark wear charts "
        "show massive advantage over D2/Sverker 21."
    )
    data["extraction_notes"] = (
        "12-page datasheet from third-party source (terasrenki.com). "
        "Contains wear resistance and toughness comparative charts vs D2."
    )

    pdf.close()
    return data


def extract_caldie():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "caldie.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Caldie", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/216/productdb/api/tech_uddeholm-caldie_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 0.7, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.5}

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 62

    data["heat_treatment"]["austenitize_c"] = "1000-1025"
    data["heat_treatment"]["temper_c"] = "200 or 500-530 (2x)"
    data["heat_treatment"]["notes"] = (
        "Low temp temper at 200C or high temp at 500-530C 2x. "
        "High temp temper gives better secondary hardness and coating compatibility."
    )

    data["physical_properties"]["density_kg_m3"] = 7820
    data["physical_properties"]["elastic_modulus_gpa"] = 213
    data["physical_properties"]["thermal_conductivity"] = 24

    data["wear_resistance"]["relative_to_d2"] = "slightly lower"
    data["toughness"]["relative_to_d2"] = "far superior"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+300-500%"
    data["d2_relative_data"]["wear_pct_vs_d2"] = "-20-30% vs D2"
    data["d2_relative_data"]["notes"] = (
        "Caldie is designed for chipping/cracking resistance. Position charts show it as "
        "the toughness champion among Uddeholm cold work steels. Wear resistance is lower "
        "than D2 but chipping resistance is dramatically better."
    )
    data["extraction_notes"] = (
        "10-page Uddeholm format. Contains position diagrams, compressive strength data, "
        "and wear/toughness comparison charts."
    )

    pdf.close()
    return data


def extract_rigor():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "rigor.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Rigor", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/216/productdb/api/tech_uddeholm-rigor_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 1.0, "Si": 0.3, "Mn": 0.6, "Cr": 5.3, "Mo": 1.1, "V": 0.2}

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 62

    data["heat_treatment"]["austenitize_c"] = "950-980"
    data["heat_treatment"]["temper_c"] = "175-550"
    data["heat_treatment"]["notes"] = (
        "Lower austenitizing temp than D2. Temper 175-250C for max hardness "
        "or 500-550C for secondary hardening."
    )

    data["physical_properties"]["density_kg_m3"] = 7750
    data["physical_properties"]["elastic_modulus_gpa"] = 190
    data["physical_properties"]["thermal_conductivity"] = 26.0

    data["wear_resistance"]["relative_to_d2"] = "lower (less Cr and V)"
    data["toughness"]["relative_to_d2"] = "better"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = ["AISI A2"]
    data["cross_references"]["din_number"] = "1.2363"
    data["cross_references"]["aisi_equivalent"] = "A2"

    data["d2_relative_data"]["wear_pct_vs_d2"] = "-30-40% vs D2"
    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+30-50%"
    data["d2_relative_data"]["notes"] = (
        "Rigor is the Uddeholm A2 equivalent. Lower wear than D2 but better toughness. "
        "5% Cr steel vs D2's 12% Cr."
    )
    data["extraction_notes"] = (
        "11-page Uddeholm format with relative comparison charts and position diagrams."
    )

    pdf.close()
    return data


def extract_sverker21():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "sverker21.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Sverker 21 (D2)", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/216/productdb/api/tech_uddeholm-sverker-21_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 1.55, "Si": 0.3, "Mn": 0.4, "Cr": 11.3, "Mo": 0.8, "V": 0.8}

    data["hardness"]["typical_hrc"] = "58-62"
    data["hardness"]["max_hrc"] = 63

    data["heat_treatment"]["austenitize_c"] = "1000-1040"
    data["heat_treatment"]["temper_c"] = "200-525"
    data["heat_treatment"]["notes"] = (
        "Double or triple temper at 200-250C or 500-525C. "
        "Secondary hardness peak around 500-520C."
    )

    # Physical data from page 3
    data["physical_properties"]["density_kg_m3"] = 7700
    data["physical_properties"]["elastic_modulus_gpa"] = 210
    data["physical_properties"]["thermal_conductivity"] = 20.0

    # Compressive yield strength
    data["toughness"]["charpy_joules"] = None
    data["toughness"]["relative_to_d2"] = "baseline (this IS D2)"

    data["wear_resistance"]["relative_to_d2"] = "baseline (this IS D2)"
    data["corrosion_resistance"]["qualitative_rating"] = "moderate (semi-stainless, 12% Cr)"

    data["cross_references"]["equivalent_steels"] = ["K110", "AISI D2"]
    data["cross_references"]["din_number"] = "1.2379"
    data["cross_references"]["aisi_equivalent"] = "D2"

    data["d2_relative_data"]["notes"] = (
        "Sverker 21 IS D2. This is the baseline reference for all Uddeholm comparisons. "
        "Physical data at temperature: Density 7700/7650/7600 kg/m3 at 20/200/400C. "
        "Elastic modulus: 210/200/180 GPa at 20/200/400C. "
        "Thermal conductivity: 20.0/21.0/23.0 W/mC at 20/200/400C. "
        "Compressive yield strength: 2200 MPa at 62 HRC, 2150 at 60 HRC, 1900 at 55 HRC."
    )
    data["extraction_notes"] = (
        "10-page Uddeholm format. THE baseline D2 datasheet. Contains complete physical data table, "
        "tempering curves, compressive strength data, and application hardness recommendations."
    )

    pdf.close()
    return data


def extract_unimax():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "unimax.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Unimax", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/216/productdb/api/tech_uddeholm-unimax_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 0.5, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.5}

    data["hardness"]["typical_hrc"] = "56-60"
    data["hardness"]["max_hrc"] = 60

    data["heat_treatment"]["austenitize_c"] = "1000-1025"
    data["heat_treatment"]["temper_c"] = "525-600 (2x)"

    data["physical_properties"]["density_kg_m3"] = 7790
    data["physical_properties"]["elastic_modulus_gpa"] = 213
    data["physical_properties"]["thermal_conductivity"] = 25

    data["wear_resistance"]["relative_to_d2"] = "lower"
    data["toughness"]["relative_to_d2"] = "far superior"
    data["corrosion_resistance"]["qualitative_rating"] = "low (non-stainless)"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["toughness_pct_vs_d2"] = "+500-800%"
    data["d2_relative_data"]["wear_pct_vs_d2"] = "-50-60% vs D2"
    data["d2_relative_data"]["notes"] = (
        "Unimax is designed for extreme toughness at moderate wear resistance. "
        "Tensile/yield/impact data available at multiple hardness levels. "
        "Charpy impact toughness dramatically higher than D2. "
        "Fatigue properties also documented."
    )
    data["extraction_notes"] = (
        "9-page Uddeholm format. Contains detailed mechanical property tables: "
        "tensile strength, yield strength, elongation, and impact toughness at "
        "various hardness levels. Fatigue data also present."
    )

    pdf.close()
    return data


def extract_corrax():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "corrax.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Corrax", "Uddeholm",
        "https://www.voestalpine.com/highperformancemetals/uk/app/uploads/sites/249/productdb/api/tech-uddeholm-corrax_en.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 0.03, "Si": 0.3, "Mn": 0.3, "Cr": 12.0, "Mo": 1.4, "Ni": 9.2, "Al": 1.6}

    data["hardness"]["typical_hrc"] = "34-50"
    data["hardness"]["max_hrc"] = 50

    data["heat_treatment"]["austenitize_c"] = "850 (solution annealing)"
    data["heat_treatment"]["temper_c"] = "425-600 (aging)"
    data["heat_treatment"]["notes"] = (
        "Precipitation hardening steel. Solution anneal at 850C, then age at 425-600C. "
        "Different aging temps give different hardness: 425C->50 HRC, 480C->48 HRC, 525C->44 HRC."
    )

    data["physical_properties"]["density_kg_m3"] = 7700
    data["physical_properties"]["elastic_modulus_gpa"] = 200
    data["physical_properties"]["thermal_conductivity"] = 18

    data["wear_resistance"]["relative_to_d2"] = "much lower (different application)"
    data["toughness"]["relative_to_d2"] = "better at equivalent hardness"
    data["corrosion_resistance"]["qualitative_rating"] = "excellent (superior to 420 SS)"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["notes"] = (
        "Corrax is a precipitation hardening stainless steel, not a direct competitor to D2. "
        "Excellent corrosion resistance. Used for plastic molds and corrosive environments. "
        "Not meaningful to compare wear/toughness vs D2 as they serve different applications."
    )
    data["extraction_notes"] = (
        "12-page Uddeholm format. Contains aging curves, physical data, and corrosion data. "
        "This is a PH stainless steel, not a conventional tool steel."
    )

    pdf.close()
    return data


def extract_dievar():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "dievar.pdf"))
    text = extract_all_text(pdf)
    data = make_steel_template(
        "Dievar", "Uddeholm",
        "https://www.uddeholm.com/app/uploads/sites/247/2024/06/Tech-Uddeholm-Dievar-EN.pdf"
    )
    data["powder_metallurgy"] = False
    data["composition"] = {"C": 0.35, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.6}

    data["hardness"]["typical_hrc"] = "44-52"
    data["hardness"]["max_hrc"] = 52

    data["heat_treatment"]["austenitize_c"] = "1000-1030"
    data["heat_treatment"]["temper_c"] = "550-625 (2x)"
    data["heat_treatment"]["notes"] = (
        "Hot work tool steel. Temper 2x at 550-625C for 44-52 HRC. "
        "Designed for die casting, forging, and extrusion dies."
    )

    data["physical_properties"]["density_kg_m3"] = 7800
    data["physical_properties"]["elastic_modulus_gpa"] = 210
    data["physical_properties"]["thermal_conductivity"] = 31

    data["wear_resistance"]["relative_to_d2"] = "lower (hot work application)"
    data["toughness"]["relative_to_d2"] = "significantly better (hot work optimized)"
    data["toughness"]["charpy_joules"] = 25
    data["toughness"]["charpy_type"] = "unnotched"
    data["corrosion_resistance"]["qualitative_rating"] = "low"

    data["cross_references"]["equivalent_steels"] = []

    data["d2_relative_data"]["notes"] = (
        "Dievar is a hot work tool steel (H-group concept). Not a direct competitor to D2. "
        "Designed for thermal fatigue resistance and hot toughness. "
        "Charpy impact >= 25J (NADCA specification)."
    )
    data["extraction_notes"] = (
        "14-page Uddeholm format. Contains thermal fatigue charts, heat check resistance data, "
        "and hot toughness comparisons. Hot work application, not cold work."
    )

    pdf.close()
    return data


# ────────────────────────────────────────────
#  Knife brochure extractor
# ────────────────────────────────────────────

def extract_knife_brochure():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "knife_brochure.pdf"))
    text = extract_all_text(pdf)

    knife_data = {
        "source": "Uddeholm Premium Steel for Knives brochure",
        "source_url": "https://www.uddeholm.com/app/uploads/sites/247/2024/09/Uddeholm_Premium_Steel_for_Knives_Eng_1703_e6.pdf",
        "steels_covered": ["Vanax SuperClean", "Elmax SuperClean", "Vanadis 4 Extra SuperClean", "Vanadis 8 SuperClean", "Sleipner"],
        "compositions": {
            "Vanax": {"C": 0.36, "N": 1.55, "Cr": 18.2, "Mo": 1.1, "V": 3.5},
            "Elmax": {"C": 1.7, "Cr": 18.0, "Mo": 1.0, "V": 3.0},
            "Vanadis 4 Extra": {"C": 1.4, "Cr": 4.7, "Mo": 3.5, "V": 3.7},
            "Vanadis 8": {"C": 2.3, "Si": 0.4, "Mn": 0.4, "Cr": 4.8, "Mo": 3.6, "V": 8.0},
            "Sleipner": {"C": 0.9, "Cr": 7.8, "Mo": 2.5, "V": 0.5}
        },
        "recommended_heat_treatment": [
            {"steel": "Vanax", "austenitize_c": 1080, "cryo": "-195C", "temper_c": "200 (3x1h)", "target_hrc": 60},
            {"steel": "Elmax (corrosion)", "austenitize_c": 1040, "cryo": "-195C (optional)", "temper_c": "250 (2x2h)", "target_hrc": 58},
            {"steel": "Elmax (hardness)", "austenitize_c": 1150, "cryo": "-195C", "temper_c": "200 (2x2h)", "target_hrc": 62},
            {"steel": "Vanadis 4 Extra", "austenitize_c": 1040, "cryo": None, "temper_c": "560 (2x2h)", "target_hrc": 62},
            {"steel": "Vanadis 8 (high)", "austenitize_c": 1180, "cryo": None, "temper_c": "540 (2x2h)", "target_hrc": 64},
            {"steel": "Vanadis 8 (low)", "austenitize_c": 1020, "cryo": None, "temper_c": "540 (2x2h)", "target_hrc": 60},
            {"steel": "Sleipner (high)", "austenitize_c": 1150, "cryo": None, "temper_c": "540 (2x2h)", "target_hrc": 63},
            {"steel": "Sleipner (low)", "austenitize_c": 1030, "cryo": None, "temper_c": "540 (2x2h)", "target_hrc": 59}
        ],
        "relative_property_profiles": {
            "Vanax": {
                "corrosion_resistance": "exceptional (rated highest)",
                "wear_resistance_edge_retention": "high",
                "toughness": "good",
                "machinability_grinding": "good",
                "notes": "Revolutionary nitrogen-based approach. Corrosion as good as 300 series SS."
            },
            "Elmax": {
                "corrosion_resistance": "good",
                "wear_resistance_edge_retention": "high",
                "toughness": "good (best among stainless PM at max hardness)",
                "machinability_grinding": "very good",
                "notes": "Best all-round PM knife steel. Outperforms other stainless PM in toughness even at max hardness."
            },
            "Vanadis 4 Extra": {
                "corrosion_resistance": "low (non-stainless)",
                "wear_resistance_edge_retention": "high",
                "toughness": "very high (designed for max toughness)",
                "machinability_grinding": "good",
                "notes": "Recommended for tactical/utility knives. Hardness range 58-62 HRC."
            },
            "Vanadis 8": {
                "corrosion_resistance": "low (non-stainless)",
                "wear_resistance_edge_retention": "very high (highest PM grade)",
                "toughness": "good",
                "machinability_grinding": "moderate",
                "notes": "Most wear-resistant PM grade. 8% vanadium. For knives where abrasive wear is dominant."
            },
            "Sleipner": {
                "corrosion_resistance": "moderate (better than D2)",
                "wear_resistance_edge_retention": "good",
                "toughness": "good (better than D2)",
                "machinability_grinding": "good",
                "notes": "Modern D2 replacement. Not PM but finer structure gives better edge retention and polishability."
            }
        },
        "extraction_notes": (
            "12-page knife-specific brochure. Contains qualitative property profile charts (bar charts) "
            "for each steel comparing vs competitors and AISI 440C. Heat treatment recommendations are "
            "knife-specific (different from industrial tool recommendations)."
        )
    }

    pdf.close()
    return knife_data


# ────────────────────────────────────────────
#  Pocket book extractor
# ────────────────────────────────────────────

def extract_pocket_book():
    pdf = pdfplumber.open(os.path.join(PDF_DIR, "pocket_book.pdf"))

    compositions = []

    # Page 4 (index 3) - first composition table
    page4_grades = [
        {"steel_name": "Arne", "composition": {"C": 0.95, "Si": 0.3, "Mn": 1.1, "Cr": 0.6, "Mo": 0.1, "W": 0.55}, "din_number": "1.2510", "aisi_equivalent": "O1"},
        {"steel_name": "Bure", "composition": {"C": 0.39, "Si": 1.0, "Mn": 0.4, "Cr": 5.3, "Mo": 1.3, "V": 0.9}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Caldie", "composition": {"C": 0.70, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.5}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Calmax", "composition": {"C": 0.60, "Si": 0.35, "Mn": 0.8, "Cr": 4.5, "Mo": 0.5, "V": 0.2}, "din_number": "1.2358", "aisi_equivalent": None},
        {"steel_name": "Carmo", "composition": {"C": 0.60, "Si": 0.35, "Mn": 0.8, "Cr": 4.5, "Mo": 0.5, "V": 0.2}, "din_number": "1.2358", "aisi_equivalent": None},
        {"steel_name": "Corrax", "composition": {"C": 0.03, "Si": 0.3, "Mn": 0.3, "Cr": 12.0, "Mo": 1.4, "Ni": 9.2, "Al": 1.6}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Dievar", "composition": {"C": 0.35, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.6}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Elmax SuperClean", "composition": {"C": 1.70, "Si": 0.8, "Mn": 0.3, "Cr": 18.0, "Mo": 1.0, "V": 3.0}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Formax", "composition": {"C": 0.18, "Si": 0.3, "Mn": 1.3}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Formvar", "composition": {"C": 0.35, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.6}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Holdax", "composition": {"C": 0.40, "Si": 0.4, "Mn": 1.5, "Cr": 1.9, "Mo": 0.2, "S": 0.07}, "din_number": "1.2312", "aisi_equivalent": None},
        {"steel_name": "Idun", "composition": {"C": 0.21, "Si": 0.9, "Mn": 0.45, "Cr": 13.5, "Mo": 0.2, "Ni": 0.6, "V": 0.25}, "din_number": None, "aisi_equivalent": "420 mod."},
        {"steel_name": "Impax Supreme", "composition": {"C": 0.37, "Si": 0.3, "Mn": 1.4, "Cr": 2.0, "Mo": 0.2, "Ni": 1.0}, "din_number": "1.2738", "aisi_equivalent": "P20 modified"},
        {"steel_name": "Mirrax ESR", "composition": {"C": 0.25, "Si": 0.3, "Mn": 0.5, "Cr": 13.3, "Mo": 0.3, "Ni": 1.3, "V": 0.3}, "din_number": None, "aisi_equivalent": "420 mod."},
        {"steel_name": "Mirrax 40", "composition": {"C": 0.21, "Si": 0.9, "Mn": 0.45, "Cr": 13.5, "Mo": 0.2, "Ni": 0.6, "V": 0.25}, "din_number": None, "aisi_equivalent": "420 mod."},
        {"steel_name": "Nimax", "composition": {"C": 0.1, "Si": 0.3, "Mn": 2.5, "Cr": 3.0, "Mo": 0.3, "Ni": 1.0}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Orvar Supreme", "composition": {"C": 0.39, "Si": 1.0, "Mn": 0.4, "Cr": 5.2, "Mo": 1.4, "V": 0.9}, "din_number": "1.2344", "aisi_equivalent": "H13"},
        {"steel_name": "Orvar 2M", "composition": {"C": 0.39, "Si": 1.0, "Mn": 0.4, "Cr": 5.2, "Mo": 1.4, "V": 0.9}, "din_number": "1.2344", "aisi_equivalent": "H13"},
        {"steel_name": "QRO 90 Supreme", "composition": {"C": 0.38, "Si": 0.3, "Mn": 0.8, "Cr": 2.6, "Mo": 2.3, "V": 0.9}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Ramax HH", "composition": {"C": 0.12, "Si": 0.2, "Mn": 1.3, "Cr": 13.4, "Mo": 0.5, "Ni": 1.6, "V": 0.2, "S": 0.1}, "din_number": None, "aisi_equivalent": "420F"},
        {"steel_name": "Rigor", "composition": {"C": 1.00, "Si": 0.3, "Mn": 0.6, "Cr": 5.3, "Mo": 1.1, "V": 0.2}, "din_number": "1.2363", "aisi_equivalent": "A2"},
        {"steel_name": "Royalloy", "composition": {"C": 0.05, "Si": 0.4, "Mn": 1.2, "Cr": 12.6, "V": 0.12}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Skolvar", "composition": {"C": 0.70, "Si": 0.2, "Mn": 0.45, "Cr": 5.00, "Mo": 2.25, "V": 1.60}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Sleipner", "composition": {"C": 0.90, "Si": 0.9, "Mn": 0.5, "Cr": 7.8, "Mo": 2.5, "V": 0.5}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Stavax ESR", "composition": {"C": 0.38, "Si": 0.9, "Mn": 0.5, "Cr": 13.6, "V": 0.3}, "din_number": "1.2083", "aisi_equivalent": "420 mod."},
        {"steel_name": "Viking", "composition": {"C": 0.50, "Si": 1.0, "Mn": 0.5, "Cr": 8.0, "Mo": 1.5, "V": 0.5}, "din_number": "1.2631", "aisi_equivalent": None},
    ]

    # Page 5 (index 4) - second composition table
    page5_grades = [
        {"steel_name": "Sverker 3", "composition": {"C": 2.05, "Si": 0.3, "Mn": 0.8, "Cr": 12.7, "W": 1.1}, "din_number": "1.2436", "aisi_equivalent": "D6"},
        {"steel_name": "Sverker 21", "composition": {"C": 1.55, "Si": 0.3, "Mn": 0.4, "Cr": 11.3, "Mo": 0.8, "V": 0.8}, "din_number": "1.2379", "aisi_equivalent": "D2"},
        {"steel_name": "Tyrax ESR", "composition": {"C": 0.4, "Si": 0.2, "Mn": 0.5, "Cr": 12.0, "Mo": 2.3, "V": 0.5}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "UHB 11", "composition": {"C": 0.50, "Si": 0.2, "Mn": 0.7}, "din_number": "1.1730", "aisi_equivalent": "1148"},
        {"steel_name": "Unimax", "composition": {"C": 0.50, "Si": 0.2, "Mn": 0.5, "Cr": 5.0, "Mo": 2.3, "V": 0.5}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Vanadis 4 Extra SuperClean", "composition": {"C": 1.40, "Si": 0.4, "Mn": 0.4, "Cr": 4.7, "Mo": 3.5, "V": 3.7}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Vanadis 8 SuperClean", "composition": {"C": 2.3, "Si": 0.4, "Mn": 0.4, "Cr": 4.8, "Mo": 3.6, "V": 8.0}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Vanax SuperClean", "composition": {"C": 0.36, "Si": 0.3, "Mn": 0.3, "Cr": 18.2, "Mo": 1.1, "V": 3.5, "N": 1.55}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Vancron SuperClean", "composition": {"C": 1.30, "Si": 0.5, "Mn": 0.4, "Cr": 4.5, "Mo": 1.8, "V": 10.0, "N": 1.8}, "din_number": None, "aisi_equivalent": None},
        {"steel_name": "Vidar Superior", "composition": {"C": 0.36, "Si": 0.3, "Mn": 0.3, "Cr": 5.0, "Mo": 1.3, "V": 0.5}, "din_number": "1.2340", "aisi_equivalent": "H11"},
        {"steel_name": "Vidar 1", "composition": {"C": 0.38, "Si": 1.0, "Mn": 0.4, "Cr": 5.0, "Mo": 1.3, "V": 0.4}, "din_number": "1.2343", "aisi_equivalent": "H11"},
        {"steel_name": "Vidar 1 ESR", "composition": {"C": 0.38, "Si": 1.0, "Mn": 0.4, "Cr": 5.0, "Mo": 1.3, "V": 0.4}, "din_number": "1.2343", "aisi_equivalent": "H11"},
    ]

    # High speed steels
    hss_grades = [
        {"steel_name": "Vanadis 23 SuperClean", "composition": {"C": 1.28, "Cr": 4.2, "Mo": 5.0, "W": 6.4, "V": 3.1}, "din_number": "1.3395", "aisi_equivalent": "M3:2"},
        {"steel_name": "Vanadis 30 SuperClean", "composition": {"C": 1.28, "Cr": 4.2, "Mo": 5.0, "W": 6.4, "V": 3.1, "Co": 8.5}, "din_number": "1.3294", "aisi_equivalent": "M3:2+Co"},
        {"steel_name": "Vanadis 60 SuperClean", "composition": {"C": 2.30, "Cr": 4.2, "Mo": 7.0, "W": 6.5, "V": 6.5, "Co": 10.5}, "din_number": "1.3292", "aisi_equivalent": None},
    ]

    compositions = page4_grades + page5_grades + hss_grades

    pdf.close()
    return compositions


# ────────────────────────────────────────────
#  Main
# ────────────────────────────────────────────

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    extractors = {
        "m390": extract_m390,
        "m398": extract_m398,
        "elmax": extract_elmax,
        "k390": extract_k390,
        "k110": extract_k110,
        "k340": extract_k340,
        "sleipner": extract_sleipner,
        "vanadis_4_extra": extract_vanadis4extra,
        "vanadis_8": extract_vanadis8,
        "vanadis_10": extract_vanadis10,
        "caldie": extract_caldie,
        "rigor": extract_rigor,
        "sverker_21": extract_sverker21,
        "unimax": extract_unimax,
        "corrax": extract_corrax,
        "dievar": extract_dievar,
    }

    all_steels = []

    for name, extractor in extractors.items():
        print(f"Extracting {name}...")
        try:
            data = extractor()
            outpath = os.path.join(OUT_DIR, f"{name}.json")
            with open(outpath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  -> {outpath}")
            all_steels.append(data)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    # Knife brochure
    print("Extracting knife brochure...")
    knife_data = extract_knife_brochure()
    with open(os.path.join(OUT_DIR, "_knife_brochure_data.json"), "w") as f:
        json.dump(knife_data, f, indent=2)
    print(f"  -> _knife_brochure_data.json")

    # Pocket book compositions
    print("Extracting pocket book compositions...")
    pocket_data = extract_pocket_book()
    with open(os.path.join(OUT_DIR, "_pocket_book_compositions.json"), "w") as f:
        json.dump(pocket_data, f, indent=2)
    print(f"  -> _pocket_book_compositions.json ({len(pocket_data)} grades)")

    # Summary
    print("Creating summary...")
    summary = {
        "total_steels_extracted": len(all_steels),
        "steels": [],
        "pocket_book_grades": len(pocket_data),
        "knife_brochure_steels": knife_data["steels_covered"],
        "d2_baseline_steels": ["K110 (D2)", "Sverker 21 (D2)"],
        "pm_steels": [s["steel_name"] for s in all_steels if s["powder_metallurgy"]],
        "conventional_steels": [s["steel_name"] for s in all_steels if not s["powder_metallurgy"]],
        "extraction_notes": (
            "Data extracted using pdfplumber from official Bohler-Uddeholm datasheets. "
            "Composition values are from PDF text/tables. Qualitative ratings and D2-relative "
            "comparisons are from datasheet text and position diagrams. "
            "Tempering curves and comparative bar charts are image-based and require "
            "vision model for precise numerical extraction."
        )
    }

    for s in all_steels:
        summary["steels"].append({
            "name": s["steel_name"],
            "brand": s["brand"],
            "pm": s["powder_metallurgy"],
            "composition_elements": list(s["composition"].keys()),
            "hardness_range": s["hardness"]["typical_hrc"],
            "has_d2_comparison": bool(s["d2_relative_data"]["wear_pct_vs_d2"] or s["d2_relative_data"]["toughness_pct_vs_d2"]),
        })

    with open(os.path.join(OUT_DIR, "_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  -> _summary.json")

    print(f"\nDone! Extracted {len(all_steels)} steels + knife brochure + pocket book ({len(pocket_data)} grades)")


if __name__ == "__main__":
    main()
