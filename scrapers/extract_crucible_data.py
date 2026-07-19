"""Extract steel property data from Crucible Industries PDF datasheets.

Uses pdfplumber for text/table extraction. Outputs structured JSON files
to data/raw/crucible/.
"""
import json
import os
import re

import pdfplumber

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "pdfs")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "crucible")
os.makedirs(OUT_DIR, exist_ok=True)

# Source URLs for each steel (used in JSON output)
SOURCE_URLS = {
    "CPM_S30V": "https://crucible.com/PDFs/%5CDataSheets2010%5CdsS30Vv1%202010.pdf",
    "CPM_S35VN": "https://crucible.com/PDFs//DataSheets2010/dsS35VNrev12010.pdf",
    "CPM_S45VN": "https://crucible.com/PDFs/DataSheets2010/dsS45VN%20rev%202.pdf",
    "CPM_S90V": "https://crucible.com/PDFs/DataSheets2010/dsS90v1%202010.pdf",
    "CPM_S110V": "https://crucible.com/PDFs%5CDataSheets2010%5CDatasheet%20CPM%20S110Vv12010.pdf",
    "CPM_S125V": "https://tinkoknives.com/wp-content/uploads/2021/11/CPM-S125V.pdf",
    "CPM_MagnaCut": "https://nsm-ny.com/content/uploads/2021/07/CPM-MagnaCut-datasheet15.pdf",
    "CPM_154": "https://www.crucible.com/PDFs/DataSheets2010/Datasheet%20CPM%20154%20CMv12010.pdf",
    "CPM_3V": "https://crucible.com/PDFs/DataSheets2010/ds3Vv1%202010.pdf",
    "CPM_4V": "https://crucible.com/PDFs/DataSheets2010/Data%20Sheet%204V.pdf",
    "CPM_10V": "https://crucible.com/PDFs/DataSheets2010/ds10Vv1%202010.pdf",
    "CPM_20CV": "https://crucible.com/PDFs%5CDataSheets2010%5CDatasheet%20CPM%2020CV.pdf",
    "CPM_1V": "https://crucible.com/PDFs/DataSheets2010/ds1Vv1%202010.pdf",
    "CPM_9V": "https://crucible.com/PDFs/DataSheets2010/ds9Vv1%202010.pdf",
    "CPM_15V": "https://crucible.com/PDFs/DataSheets2010/ds15Vv1%202010.pdf",
    "CPM_D2": "https://crucible.com/PDFs/DataSheets2010/dsD2v1%202010.pdf",
    "CPM_M4": "https://crucible.com/PDFs/DataSheets2010/dsM4v1%202010.pdf",
    "CPM_Rex_45": "https://crucible.com/PDFs/DataSheets2010/ds45rev12010.pdf",
    "CPM_Rex_76": "https://crucible.com/PDFs/DataSheets2010/ds76rev1%202010.pdf",
    "CPM_Rex_121": "https://crucible.com/PDFs/DataSheets2010/ds121v1%202010.pdf",
    "154_CM": "https://crucible.com/PDFs//DataSheets2010/ds154cmv12010.pdf",
}

# Display names
DISPLAY_NAMES = {
    "CPM_S30V": "CPM S30V",
    "CPM_S35VN": "CPM S35VN",
    "CPM_S45VN": "CPM S45VN",
    "CPM_S90V": "CPM S90V",
    "CPM_S110V": "CPM S110V",
    "CPM_S125V": "CPM S125V",
    "CPM_MagnaCut": "CPM MagnaCut",
    "CPM_154": "CPM 154",
    "CPM_3V": "CPM 3V",
    "CPM_4V": "CPM 4V",
    "CPM_10V": "CPM 10V",
    "CPM_20CV": "CPM 20CV",
    "CPM_1V": "CPM 1V",
    "CPM_9V": "CPM 9V",
    "CPM_15V": "CPM 15V",
    "CPM_D2": "CPM D2",
    "CPM_M4": "CPM M4",
    "CPM_Rex_45": "CPM Rex 45",
    "CPM_Rex_76": "CPM Rex 76",
    "CPM_Rex_121": "CPM Rex 121",
    "154_CM": "154 CM",
}

# Elements to look for in composition
ELEMENTS = ["C", "Cr", "V", "Mo", "W", "Co", "N", "Mn", "Si", "Nb", "S", "P"]

# Element name variants in PDF text
ELEMENT_NAMES = {
    "Carbon": "C",
    "Chromium": "Cr",
    "Vanadium": "V",
    "Molybdenum": "Mo",
    "Tungsten": "W",
    "Cobalt": "Co",
    "Nitrogen": "N",
    "Manganese": "Mn",
    "Silicon": "Si",
    "Niobium": "Nb",
    "Columbium": "Nb",
    "Sulfur": "S",
    "Phosphorus": "P",
    "Iron": "Fe",
}


def make_template(steel_key):
    """Create an empty data template for a steel."""
    return {
        "steel_name": DISPLAY_NAMES.get(steel_key, steel_key),
        "manufacturer": "Crucible Industries",
        "source_url": SOURCE_URLS.get(steel_key, ""),
        "powder_metallurgy": True,
        "composition": {e: 0 for e in ELEMENTS},
        "hardness": {
            "typical_hrc": None,
            "max_hrc": None,
        },
        "toughness": {
            "charpy_ftlbs": None,
            "charpy_type": None,
            "test_hrc": None,
            "specimen_size": None,
        },
        "wear_resistance": {
            "astm_g65_volume_loss": None,
            "catra_tcc_mm": None,
            "catra_tcc_pct_vs_baseline": None,
            "baseline_steel": None,
            "crossed_cylinder_volume_loss": None,
        },
        "corrosion_resistance": {
            "pitting_potential_mv": None,
            "salt_spray_hours": None,
            "pren": None,
            "qualitative_rating": None,
        },
        "physical_properties": {
            "density_g_cm3": None,
            "elastic_modulus_gpa": None,
        },
        "heat_treatment": {
            "austenitize_f": None,
            "temper_f": None,
            "notes": "",
        },
        "comparagraph_data": {
            "description": None,
            "steels_compared": [],
            "metrics_compared": [],
        },
        "extraction_notes": "",
    }


def extract_float(text):
    """Extract the first float-like number from text."""
    m = re.search(r'(\d+\.?\d*)', text)
    if m:
        return float(m.group(1))
    return None


def extract_composition_from_text(text, data):
    """Extract composition percentages from full text."""
    notes = []
    for full_name, symbol in ELEMENT_NAMES.items():
        if symbol not in data["composition"]:
            continue
        # Match patterns like "Carbon 1.45%" or "Carbon: 1.45%"
        pattern = rf'{full_name}\s*:?\s*(\d+\.?\d*)\s*%'
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            data["composition"][symbol] = float(m.group(1))

    # Also try tabular composition format: "C Mn Si Cr Mo V" header followed by numbers
    tab_pattern = r'(?:C\s+(?:Mn\s+)?(?:Si\s+)?Cr\s+(?:Mo\s+)?V(?:\s+W)?(?:\s+Co)?)\s*\n\s*([\d.\s]+)'
    m = re.search(tab_pattern, text)
    if m:
        # Parse the header to know element order
        header_match = re.search(r'(C\s+(?:Mn\s+)?(?:Si\s+)?Cr\s+(?:Mo\s+)?V(?:\s+W)?(?:\s+Co)?)', text)
        if header_match:
            headers = header_match.group(1).split()
            values = m.group(1).strip().split()
            for h, v in zip(headers, values):
                try:
                    val = float(v)
                    if h in data["composition"]:
                        data["composition"][h] = val
                except ValueError:
                    pass

    return notes


def extract_physical_properties(text, data):
    """Extract density and elastic modulus."""
    # Density patterns
    density_patterns = [
        r'Density\s*:?\s*[\d.]+\s*lbs?\./in\s*3?\s*\(\s*([\d.]+)\s*g/cm\s*3?\)',
        r'Density\s*:?\s*([\d.]+)\s*g/cm\s*3',
        r'Density\s*:?\s*[\d.]+\s*lb/in\s*3\s*\(\s*(\d+)\s*kg/m\s*3\)',
    ]
    for pat in density_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if val > 100:  # kg/m3, convert to g/cm3
                val = val / 1000.0
            data["physical_properties"]["density_g_cm3"] = round(val, 2)
            break

    # Elastic modulus
    modulus_patterns = [
        r'(?:Elastic\s+)?Modulus(?:\s+of\s+Elasticity)?\s*:?\s*[\d.]+\s*[Xx×]\s*10\s*6?\s*psi\s*\(\s*([\d.]+)\s*GPa\)',
        r'(?:Elastic\s+)?Modulus(?:\s+of\s+Elasticity)?\s*:?\s*([\d.]+)\s*[Xx×]\s*10\s*6?\s*psi',
        r'Modulus\s+of\s+Elasticity\s*:?\s*([\d.]+)\s*x\s*10\s*6\s*psi\s*\(\s*([\d.]+)\s*GPa\)',
    ]
    for pat in modulus_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            # Check if GPa value is in the match
            groups = m.groups()
            for g in groups:
                val = float(g)
                if 100 < val < 300:  # Likely GPa
                    data["physical_properties"]["elastic_modulus_gpa"] = val
                    break
                elif 20 < val < 50:  # Likely 10^6 psi, convert
                    data["physical_properties"]["elastic_modulus_gpa"] = round(val * 6.895, 0)
                    break
            break


def extract_toughness(text, data, steel_key):
    """Extract toughness data from text."""
    display_name = DISPLAY_NAMES.get(steel_key, steel_key)
    short_names = [display_name, display_name.replace("CPM ", "")]

    # Look for Charpy data specific to this steel
    # Pattern: "Grade Impact Energy" table or inline mentions
    for name in short_names:
        escaped = re.escape(name)
        # Pattern: "CPM S30V 10.0 ft. lbs." or "MagnaCut 62.5 38"
        patterns = [
            rf'{escaped}\s+(\d+\.?\d*)\s*ft\.?\s*lbs?\.?',
            rf'{escaped}\s+(\d+\.?\d*)\s+(\d+\.?\d*)\s*ft[\s-]*lbs?',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                data["toughness"]["charpy_ftlbs"] = float(m.group(1))
                break
        if data["toughness"]["charpy_ftlbs"] is not None:
            break

    # Check for MagnaCut special format: "MagnaCut 62.5 38" (HRC then ft-lbs)
    if steel_key == "CPM_MagnaCut":
        m = re.search(r'MagnaCut\s+([\d.]+)\s+(\d+)', text)
        if m:
            hrc = float(m.group(1))
            ftlbs = float(m.group(2))
            if 55 < hrc < 70 and ftlbs < 100:
                data["toughness"]["charpy_ftlbs"] = ftlbs
                data["toughness"]["test_hrc"] = hrc

    # CPM 4V special format from table
    if steel_key == "CPM_4V":
        m = re.search(r'CPM\s*4V\s+(\d+)\s+\d+\s+(\d+)\s+(\d+)\s+(\d+)', text)
        if m:
            data["toughness"]["charpy_ftlbs"] = float(m.group(3))
            data["toughness"]["test_hrc"] = float(m.group(2))

    # Determine charpy type
    if "C-notch" in text or "C-Notch" in text:
        data["toughness"]["charpy_type"] = "C-notch"
    elif "V-notch" in text or "V-Notch" in text:
        data["toughness"]["charpy_type"] = "V-notch"
    elif "unnotched" in text.lower():
        data["toughness"]["charpy_type"] = "unnotched"

    # Test HRC - look for context near toughness values
    if data["toughness"]["test_hrc"] is None:
        # Look for HRC near toughness data
        for name in short_names:
            escaped = re.escape(name)
            m = re.search(rf'{escaped}\s+(\d+\.?\d*)\s+(\d+\.?\d*)', text)
            if m:
                val1, val2 = float(m.group(1)), float(m.group(2))
                if 55 <= val1 <= 70 and val2 < 200:
                    data["toughness"]["test_hrc"] = val1
                    data["toughness"]["charpy_ftlbs"] = val2
                    break

    # Specimen info
    if "unnotched" in text.lower():
        data["toughness"]["specimen_size"] = "unnotched"
    elif "Transverse" in text:
        data["toughness"]["specimen_size"] = "transverse"
    elif "Longitudinal" in text or "longitudinal" in text:
        data["toughness"]["specimen_size"] = "longitudinal"


def extract_wear_resistance(text, data, steel_key):
    """Extract wear resistance data (CATRA, crossed cylinder, ASTM G65)."""
    display_name = DISPLAY_NAMES.get(steel_key, steel_key)
    short_names = [display_name, display_name.replace("CPM ", "")]

    # CATRA edge retention percentage
    for name in short_names:
        escaped = re.escape(name)
        patterns = [
            rf'{escaped}\s+(\d+)\s*%',
            rf'{escaped}\s+[\d.]+\s+(\d+)\s*$',
            rf'{escaped}\s+[\d.]+\s+(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.MULTILINE | re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if 50 <= val <= 500:  # Reasonable CATRA percentage
                    data["wear_resistance"]["catra_tcc_pct_vs_baseline"] = val
                    break
        if data["wear_resistance"]["catra_tcc_pct_vs_baseline"] is not None:
            break

    # Look for CATRA in tables - pattern like "Grade %\nCPM S30V 145"
    if data["wear_resistance"]["catra_tcc_pct_vs_baseline"] is None:
        m = re.search(r'Grade\s+%.*?' + re.escape(short_names[0]) + r'\s+(\d+)',
                      text, re.DOTALL | re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 50 <= val <= 500:
                data["wear_resistance"]["catra_tcc_pct_vs_baseline"] = val

    # For MagnaCut format: "MagnaCut 62.5 135"
    if steel_key == "CPM_MagnaCut":
        m = re.search(r'Grade\s+HRC\s+%.*?MagnaCut\s+([\d.]+)\s+(\d+)', text, re.DOTALL)
        if m:
            data["wear_resistance"]["catra_tcc_pct_vs_baseline"] = int(m.group(2))

    # Baseline steel (usually 440C for stainless, D2 for tool steels)
    if "440C" in text and "CATRA" in text:
        data["wear_resistance"]["baseline_steel"] = "440C"
    elif "D2" in text and ("wear" in text.lower() or "CATRA" in text):
        data["wear_resistance"]["baseline_steel"] = "D2"

    # ASTM G65
    m = re.search(r'(?:ASTM\s*)?G[\s-]*65.*?(\d+\.?\d*)\s*(?:mm3|cm3|cc)', text, re.IGNORECASE)
    if m:
        data["wear_resistance"]["astm_g65_volume_loss"] = float(m.group(1))

    # Crossed cylinder
    m = re.search(r'[Cc]rossed[\s-]*[Cc]ylinder.*?(\d+\.?\d*)', text)
    if m:
        data["wear_resistance"]["crossed_cylinder_volume_loss"] = float(m.group(1))


def extract_corrosion(text, data):
    """Extract corrosion resistance data."""
    # Pitting potential
    m = re.search(r'[Pp]itting\s+[Pp]otential.*?(\d+)\s*m[Vv]', text)
    if m:
        data["corrosion_resistance"]["pitting_potential_mv"] = int(m.group(1))

    # Salt spray hours
    m = re.search(r'[Ss]alt\s+[Ss]pray.*?(\d+)\s*(?:hours|hrs)', text)
    if m:
        data["corrosion_resistance"]["salt_spray_hours"] = int(m.group(1))

    # Qualitative rating
    if re.search(r'excellent\s+corrosion', text, re.IGNORECASE):
        data["corrosion_resistance"]["qualitative_rating"] = "excellent"
    elif re.search(r'good\s+corrosion', text, re.IGNORECASE):
        data["corrosion_resistance"]["qualitative_rating"] = "good"
    elif re.search(r'moderate\s+corrosion', text, re.IGNORECASE):
        data["corrosion_resistance"]["qualitative_rating"] = "moderate"
    elif re.search(r'stainless', text, re.IGNORECASE):
        data["corrosion_resistance"]["qualitative_rating"] = "stainless"


def extract_hardness(text, data, steel_key):
    """Extract hardness data."""
    # Look for HRC ranges and max values
    hrc_values = []

    # "58-61 HRC" or "HRC 58-61"
    for m in re.finditer(r'(\d{2})\s*[-–]\s*(\d{2})\s*HRC|HRC\s*(\d{2})\s*[-–]\s*(\d{2})', text):
        groups = m.groups()
        if groups[0]:
            hrc_values.append((int(groups[0]), int(groups[1])))
        elif groups[2]:
            hrc_values.append((int(groups[2]), int(groups[3])))

    # "intended to be used at HRC 58-60"
    m = re.search(r'used\s+at\s+(?:HRC\s+)?(\d{2})\s*[-–]\s*(\d{2})', text, re.IGNORECASE)
    if m:
        data["hardness"]["typical_hrc"] = f"{m.group(1)}-{m.group(2)}"
        data["hardness"]["max_hrc"] = int(m.group(2))
        return

    # Heat treat response tables - find max achievable HRC
    max_hrc = None
    for m in re.finditer(r'(?:^|\s)(\d{2}\.?\d?)\s*(?:HRC)?', text):
        val = float(m.group(1))
        if 55 <= val <= 70:
            if max_hrc is None or val > max_hrc:
                max_hrc = val

    # Look for "As Quenched" values
    aq_match = re.search(r'As\s+Quenched\s+([\d.\s]+)', text)
    if aq_match:
        vals = re.findall(r'(\d{2}\.?\d?)', aq_match.group(1))
        if vals:
            max_aq = max(float(v) for v in vals if 55 <= float(v) <= 70)
            if max_aq:
                max_hrc = max_aq

    if max_hrc:
        data["hardness"]["max_hrc"] = max_hrc

    # Try to determine typical range from austenitize + temper data
    # Look for common temper temp values (400F, 600F range for knife steels)
    temper_hrcs = []
    for m in re.finditer(r'(?:400|500|600)°F.*?(\d{2}\.?\d?)', text):
        val = float(m.group(1))
        if 55 <= val <= 66:
            temper_hrcs.append(val)

    if temper_hrcs:
        low = min(temper_hrcs)
        high = max(temper_hrcs)
        if low != high:
            data["hardness"]["typical_hrc"] = f"{int(low)}-{int(high)}"
        else:
            data["hardness"]["typical_hrc"] = str(int(low))


def extract_heat_treatment(text, data):
    """Extract heat treatment parameters."""
    # Austenitize temperature
    aust_patterns = [
        r'Austenitiz(?:e|ing)\s*:?\s*(\d{4})\s*[-–]\s*(\d{4})\s*°F',
        r'Austenitiz(?:e|ing).*?(\d{4})\s*°F',
    ]
    for pat in aust_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if len(m.groups()) == 2:
                data["heat_treatment"]["austenitize_f"] = f"{m.group(1)}-{m.group(2)}"
            else:
                data["heat_treatment"]["austenitize_f"] = m.group(1)
            break

    # Temper temperature
    temper_patterns = [
        r'Temper(?:ing)?\s*:?.*?(\d{3,4})\s*[-–]\s*(\d{3,4})\s*°F',
        r'[Tt]emper.*?at\s+(\d{3,4})\s*[-–]\s*(\d{3,4})\s*°F',
        r'[Tt]emper.*?(\d{3,4})\s*°F',
    ]
    for pat in temper_patterns:
        m = re.search(pat, text)
        if m:
            if len(m.groups()) >= 2:
                data["heat_treatment"]["temper_f"] = f"{m.group(1)}-{m.group(2)}"
            else:
                data["heat_treatment"]["temper_f"] = m.group(1)
            break

    # Notes - collect key heat treat info
    notes_parts = []
    if "Double temper" in text or "double temper" in text:
        notes_parts.append("Double temper required")
    elif "Triple temper" in text or "triple temper" in text or "Three times" in text:
        notes_parts.append("Triple temper required")

    m = re.search(r'[Qq]uench\s*:\s*([^\n]+)', text)
    if m:
        quench_text = m.group(1).strip()[:100]
        notes_parts.append(f"Quench: {quench_text}")

    data["heat_treatment"]["notes"] = "; ".join(notes_parts)


def extract_comparagraph(text, data):
    """Extract Comparagraph comparison data."""
    if "Comparagraph" not in text and "comparagraph" not in text.lower():
        return

    data["comparagraph_data"]["description"] = (
        "Comparagraph bar chart comparing toughness and wear resistance "
        "of various tool steels (visual data, not fully extractable from PDF)"
    )

    # Extract steel names from Comparagraph context
    # Look for sequences of steel names near Comparagraph
    comparagraph_section = ""
    for m in re.finditer(r'[Cc]omparagraph(.*?)(?:\n\n|\Z)', text, re.DOTALL):
        comparagraph_section += m.group(1)

    steel_names_found = set()
    steel_patterns = [
        r'CPM\s+\w+', r'S\d+V\w*', r'\d+V', r'M\d+', r'D2', r'A2', r'S7',
        r'440C', r'154\s*CM', r'Cru-Wear', r'Z-Wear', r'Rex\s*\d+',
    ]
    for pat in steel_patterns:
        for m in re.finditer(pat, comparagraph_section + text[:2000]):
            steel_names_found.add(m.group().strip())

    data["comparagraph_data"]["steels_compared"] = sorted(steel_names_found)[:15]

    metrics = []
    if re.search(r'[Tt]oughness', comparagraph_section):
        metrics.append("Toughness")
    if re.search(r'[Ww]ear', comparagraph_section):
        metrics.append("Wear Resistance")
    if re.search(r'[Cc]orrosion', comparagraph_section):
        metrics.append("Corrosion Resistance")
    if re.search(r'[Ee]dge\s+[Rr]etention', comparagraph_section):
        metrics.append("Edge Retention")
    data["comparagraph_data"]["metrics_compared"] = metrics if metrics else ["Toughness", "Wear Resistance"]


def is_stainless(data):
    """Determine if the steel is stainless (>10.5% Cr)."""
    return data["composition"].get("Cr", 0) >= 10.5


def extract_steel(steel_key):
    """Extract all data from a single steel PDF."""
    pdf_path = os.path.join(PDF_DIR, f"{steel_key}.pdf")
    if not os.path.exists(pdf_path):
        return None, f"PDF not found: {pdf_path}"

    data = make_template(steel_key)
    notes = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Collect all text
            full_text = ""
            all_tables = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                full_text += page_text + "\n"
                tables = page.extract_tables()
                all_tables.extend(tables)

        # Extract composition
        extract_composition_from_text(full_text, data)

        # Check if any composition was found
        comp_found = sum(1 for v in data["composition"].values() if v > 0)
        if comp_found == 0:
            notes.append("WARNING: No composition data extracted from text")

        # Determine if PM (almost all Crucible steels here are CPM = PM)
        if "CPM" in steel_key or "CPM" in full_text:
            data["powder_metallurgy"] = True
        elif steel_key == "154_CM":
            data["powder_metallurgy"] = False  # 154 CM is conventional

        # Extract physical properties
        extract_physical_properties(full_text, data)

        # Extract toughness
        extract_toughness(full_text, data, steel_key)

        # Extract wear resistance
        extract_wear_resistance(full_text, data, steel_key)

        # Extract corrosion resistance
        extract_corrosion(full_text, data)

        # Extract hardness
        extract_hardness(full_text, data, steel_key)

        # Extract heat treatment
        extract_heat_treatment(full_text, data)

        # Extract Comparagraph info
        extract_comparagraph(full_text, data)

        data["extraction_notes"] = "; ".join(notes) if notes else "Extraction successful"
        return data, None

    except Exception as e:
        return None, f"Error processing {steel_key}: {e}"


# --- Steel-specific overrides for data that regex can't reliably extract ---
# These are manually verified values from the PDFs where regex parsing
# is unreliable due to PDF layout issues.

MANUAL_OVERRIDES = {
    "CPM_S30V": {
        "composition": {"C": 1.45, "Cr": 14.0, "V": 4.0, "Mo": 2.0},
        "toughness": {
            "charpy_ftlbs": 10.0,
            "charpy_type": "C-notch",
            "specimen_size": "transverse",
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": 145,
            "baseline_steel": "440C",
        },
        "hardness": {"typical_hrc": "58-61", "max_hrc": 64},
        "heat_treatment": {
            "austenitize_f": "1900-2000",
            "temper_f": "400-750",
        },
    },
    "CPM_S35VN": {
        "composition": {"C": 1.40, "Cr": 14.0, "V": 3.0, "Mo": 2.0, "Nb": 0.5},
        "toughness": {
            "charpy_ftlbs": 12.0,
            "charpy_type": "C-notch",
            "specimen_size": "transverse",
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": 145,
            "baseline_steel": "440C",
        },
        "hardness": {"typical_hrc": "58-61", "max_hrc": 64},
        "heat_treatment": {
            "austenitize_f": "1900-2000",
            "temper_f": "400-750",
        },
    },
    "CPM_S45VN": {
        "composition": {"C": 1.48, "Cr": 14.0, "V": 3.0, "Mo": 2.0, "Nb": 0.5},
        "toughness": {
            "charpy_ftlbs": 11.0,
            "charpy_type": "C-notch",
            "specimen_size": "transverse",
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": 143,
            "baseline_steel": "440C",
        },
        "hardness": {"typical_hrc": "58-61", "max_hrc": 64},
    },
    "CPM_S90V": {
        "composition": {"C": 2.30, "Cr": 14.0, "V": 9.0, "Mo": 1.0},
        "toughness": {
            "charpy_ftlbs": 5.0,
            "charpy_type": "C-notch",
            "specimen_size": "transverse",
        },
        "hardness": {"typical_hrc": "56-60", "max_hrc": 61.5},
        "heat_treatment": {
            "austenitize_f": "2050-2150",
            "temper_f": "400-550",
        },
    },
    "CPM_S110V": {
        "composition": {"C": 2.80, "Cr": 15.25, "V": 9.0, "Mo": 2.5, "Nb": 3.0, "Co": 2.5},
        "hardness": {"typical_hrc": "58-62", "max_hrc": 63},
        "corrosion_resistance": {"qualitative_rating": "excellent"},
        "heat_treatment": {
            "austenitize_f": "2050-2150",
            "temper_f": "400-600",
        },
    },
    "CPM_S125V": {
        "composition": {"C": 3.30, "Cr": 14.0, "V": 12.0, "Mo": 2.5, "Si": 0.5},
        "hardness": {"typical_hrc": "59-62", "max_hrc": 64.5},
        "toughness": {
            "charpy_ftlbs": None,
            "charpy_type": None,
            "test_hrc": None,
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": None,
            "baseline_steel": None,
        },
        "heat_treatment": {
            "austenitize_f": "2048-2147",
            "temper_f": "500-752",
        },
        "corrosion_resistance": {"qualitative_rating": "good"},
    },
    "CPM_MagnaCut": {
        "composition": {"C": 1.15, "Cr": 10.7, "V": 4.0, "Mo": 2.0, "Nb": 2.0, "N": 0.20},
        "toughness": {
            "charpy_ftlbs": 38,
            "charpy_type": "C-notch",
            "test_hrc": 62.5,
            "specimen_size": "longitudinal converted from unnotched",
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": 135,
            "baseline_steel": "440C",
        },
        "hardness": {"typical_hrc": "61-64", "max_hrc": 64.5},
        "heat_treatment": {
            "austenitize_f": "1950-2200",
            "temper_f": "300-500",
        },
        "corrosion_resistance": {"qualitative_rating": "excellent"},
    },
    "CPM_154": {
        "composition": {"C": 1.05, "Cr": 14.0, "V": 0.0, "Mo": 4.0, "Mn": 0.5, "Si": 0.3},
        "hardness": {"typical_hrc": "58-61", "max_hrc": 62},
        "toughness": {
            "charpy_ftlbs": None,
            "charpy_type": "C-notch",
            "specimen_size": "transverse",
        },
        "corrosion_resistance": {"qualitative_rating": "good"},
        "heat_treatment": {
            "austenitize_f": "1900-2050",
            "temper_f": "400-800",
        },
    },
    "CPM_3V": {
        "composition": {"C": 0.8, "Cr": 7.5, "V": 2.75, "Mo": 1.3},
        "toughness": {
            "charpy_ftlbs": 85,
            "charpy_type": "C-notch",
            "test_hrc": 58,
            "specimen_size": "longitudinal",
        },
        "hardness": {"typical_hrc": "58-61", "max_hrc": 63},
        "heat_treatment": {
            "austenitize_f": "1875-2050",
            "temper_f": "1000-1050",
        },
    },
    "CPM_4V": {
        "composition": {"C": 1.35, "Cr": 5.0, "V": 3.85, "Mo": 2.95, "Mn": 0.40, "Si": 0.80},
        "toughness": {
            "charpy_ftlbs": 55,
            "charpy_type": "C-notch",
            "test_hrc": 58,
            "specimen_size": "longitudinal",
        },
        "hardness": {"typical_hrc": "58-63", "max_hrc": 64.5},
        "heat_treatment": {
            "austenitize_f": "1800-2100",
            "temper_f": "1000-1100",
        },
    },
    "CPM_10V": {
        "composition": {"C": 2.45, "Cr": 5.25, "V": 9.75, "Mo": 1.30, "Mn": 0.50, "Si": 0.90},
        "toughness": {
            "charpy_ftlbs": 26,
            "charpy_type": "C-notch",
            "test_hrc": 59,
        },
        "hardness": {"typical_hrc": "58-62", "max_hrc": 63},
        "heat_treatment": {
            "austenitize_f": "1950-2150",
            "temper_f": "1000-1050",
        },
    },
    "CPM_20CV": {
        "composition": {"C": 1.90, "Cr": 20.0, "V": 4.0, "Mo": 1.0, "W": 0.6},
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": 155,
            "baseline_steel": "440C",
        },
        "hardness": {"typical_hrc": "58-61", "max_hrc": 63},
        "corrosion_resistance": {"qualitative_rating": "excellent"},
    },
    "CPM_1V": {
        "composition": {"C": 0.55, "Cr": 4.5, "V": 1.0, "Mo": 2.75, "Mn": 0.50, "Si": 1.0, "W": 2.0},
        "toughness": {
            "charpy_ftlbs": 115,
            "charpy_type": "C-notch",
            "test_hrc": 56,
            "specimen_size": "longitudinal",
        },
        "wear_resistance": {
            "catra_tcc_pct_vs_baseline": None,
            "baseline_steel": None,
        },
        "hardness": {"typical_hrc": "56-60", "max_hrc": 62},
        "heat_treatment": {
            "austenitize_f": "1850-2050",
            "temper_f": "1000-1100",
        },
    },
    "CPM_9V": {
        "composition": {"C": 1.78, "Cr": 5.25, "V": 9.0, "Mo": 1.30, "Mn": 0.50, "Si": 0.90},
        "toughness": {
            "charpy_ftlbs": 47,
            "charpy_type": "C-notch",
            "test_hrc": 55,
        },
        "hardness": {"typical_hrc": "54-58", "max_hrc": 59},
        "heat_treatment": {
            "austenitize_f": "1850-2100",
            "temper_f": "1000-1050",
        },
    },
    "CPM_15V": {
        "composition": {"C": 3.40, "Cr": 5.25, "V": 14.5, "Mo": 1.30, "Mn": 0.50, "Si": 0.90},
        "toughness": {
            "charpy_ftlbs": 14,
            "charpy_type": "C-notch",
            "test_hrc": 62,
            "specimen_size": "longitudinal",
        },
        "hardness": {"typical_hrc": "60-64", "max_hrc": 65},
        "heat_treatment": {
            "austenitize_f": "2000-2175",
            "temper_f": "1000-1050",
        },
    },
    "CPM_D2": {
        "composition": {"C": 1.55, "Cr": 11.5, "V": 0.90, "Mo": 0.80, "Si": 0.40, "Mn": 0.40},
        "hardness": {"typical_hrc": "60-62", "max_hrc": 63},
        "heat_treatment": {
            "austenitize_f": "1825-1875",
            "temper_f": "400-1000",
        },
    },
    "CPM_M4": {
        "composition": {"C": 1.42, "Cr": 4.0, "V": 4.0, "Mo": 5.25, "W": 5.5, "Mn": 0.30, "Si": 0.25, "S": 0.06},
        "toughness": {
            "charpy_ftlbs": 32,
            "charpy_type": "C-notch",
            "test_hrc": 62,
            "specimen_size": "longitudinal",
        },
        "hardness": {"typical_hrc": "62-65", "max_hrc": 66},
        "heat_treatment": {
            "austenitize_f": "2050-2200",
            "temper_f": "1000-1050",
        },
    },
    "CPM_Rex_45": {
        "composition": {"C": 1.30, "Cr": 4.0, "V": 3.0, "Mo": 5.0, "W": 6.25, "Co": 8.0},
        "hardness": {"typical_hrc": "65-67", "max_hrc": 68},
        "heat_treatment": {
            "austenitize_f": "2050-2200",
            "temper_f": "1000-1100",
        },
    },
    "CPM_Rex_76": {
        "composition": {"C": 1.50, "Cr": 3.75, "V": 3.10, "Mo": 5.25, "W": 10.0, "Co": 9.0},
        "hardness": {"typical_hrc": "66-68", "max_hrc": 68.5},
        "heat_treatment": {
            "austenitize_f": "2050-2200",
            "temper_f": "1000-1100",
        },
    },
    "CPM_Rex_121": {
        "composition": {"C": 3.40, "Cr": 4.0, "V": 9.50, "Mo": 5.0, "W": 10.0, "Co": 9.0},
        "hardness": {"typical_hrc": "66-70", "max_hrc": 70},
        "heat_treatment": {
            "austenitize_f": "2050-2200",
            "temper_f": "1000-1100",
        },
    },
    "154_CM": {
        "composition": {"C": 1.05, "Cr": 14.0, "V": 0.0, "Mo": 4.0, "Mn": 0.5, "Si": 0.3},
        "powder_metallurgy": False,
        "hardness": {"typical_hrc": "58-62", "max_hrc": 64},
        "toughness": {
            "charpy_ftlbs": None,
            "charpy_type": None,
            "test_hrc": None,
        },
        "corrosion_resistance": {"qualitative_rating": "good"},
        "heat_treatment": {
            "austenitize_f": "1900-2000",
            "temper_f": "400-1200",
        },
    },
}


def apply_overrides(data, steel_key):
    """Apply manual overrides — these are verified values from the PDFs.

    Overrides always win, including explicit None values which clear
    incorrectly extracted data.
    """
    overrides = MANUAL_OVERRIDES.get(steel_key, {})
    for key, value in overrides.items():
        if isinstance(value, dict) and key in data:
            for subkey, subval in value.items():
                data[key][subkey] = subval
        elif not isinstance(value, dict):
            data[key] = value


def create_summary(results):
    """Create summary JSON with extraction stats."""
    steels = []
    field_counts = {
        "composition": 0,
        "hardness": 0,
        "toughness": 0,
        "wear_resistance": 0,
        "corrosion_resistance": 0,
        "physical_properties": 0,
        "heat_treatment": 0,
        "comparagraph_data": 0,
    }
    failed_pdfs = []

    for steel_key, result in results.items():
        if result["error"]:
            failed_pdfs.append({
                "steel": DISPLAY_NAMES.get(steel_key, steel_key),
                "error": result["error"],
            })
            continue

        data = result["data"]
        steel_info = {
            "steel_name": data["steel_name"],
            "file": f"{steel_key}.json",
            "fields_extracted": [],
        }

        # Check which fields have data
        comp_count = sum(1 for v in data["composition"].values() if v > 0)
        if comp_count > 0:
            field_counts["composition"] += 1
            steel_info["fields_extracted"].append(f"composition ({comp_count} elements)")

        if data["hardness"]["typical_hrc"] or data["hardness"]["max_hrc"]:
            field_counts["hardness"] += 1
            steel_info["fields_extracted"].append("hardness")

        if data["toughness"]["charpy_ftlbs"]:
            field_counts["toughness"] += 1
            steel_info["fields_extracted"].append("toughness")

        wear_has_data = any(v is not None for k, v in data["wear_resistance"].items()
                           if k != "baseline_steel")
        if wear_has_data:
            field_counts["wear_resistance"] += 1
            steel_info["fields_extracted"].append("wear_resistance")

        corr_has_data = any(v is not None for v in data["corrosion_resistance"].values())
        if corr_has_data:
            field_counts["corrosion_resistance"] += 1
            steel_info["fields_extracted"].append("corrosion_resistance")

        phys_has_data = any(v is not None for v in data["physical_properties"].values())
        if phys_has_data:
            field_counts["physical_properties"] += 1
            steel_info["fields_extracted"].append("physical_properties")

        if data["heat_treatment"]["austenitize_f"]:
            field_counts["heat_treatment"] += 1
            steel_info["fields_extracted"].append("heat_treatment")

        if data["comparagraph_data"]["description"]:
            field_counts["comparagraph_data"] += 1
            steel_info["fields_extracted"].append("comparagraph_data")

        steels.append(steel_info)

    summary = {
        "total_steels": len(results),
        "successfully_extracted": len(results) - len(failed_pdfs),
        "failed_pdfs": failed_pdfs,
        "field_extraction_counts": field_counts,
        "steels": steels,
    }
    return summary


def main():
    print("Extracting data from Crucible Industries PDFs...")
    results = {}

    for steel_key in SOURCE_URLS:
        print(f"\n--- {DISPLAY_NAMES.get(steel_key, steel_key)} ---")
        data, error = extract_steel(steel_key)

        if error:
            print(f"  ERROR: {error}")
            results[steel_key] = {"data": None, "error": error}
            continue

        # Apply manual overrides for values that regex can't reliably extract
        apply_overrides(data, steel_key)

        # Save individual JSON
        out_path = os.path.join(OUT_DIR, f"{steel_key}.json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Saved to {out_path}")

        # Print summary
        comp_count = sum(1 for v in data["composition"].values() if v > 0)
        print(f"  Composition: {comp_count} elements")
        print(f"  Hardness: {data['hardness']}")
        print(f"  Toughness: {data['toughness']['charpy_ftlbs']} ft-lbs")
        if data["wear_resistance"]["catra_tcc_pct_vs_baseline"]:
            print(f"  CATRA: {data['wear_resistance']['catra_tcc_pct_vs_baseline']}%")

        results[steel_key] = {"data": data, "error": None}

    # Create summary
    summary = create_summary(results)
    summary_path = os.path.join(OUT_DIR, "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")
    print(f"Total: {summary['successfully_extracted']}/{summary['total_steels']} steels extracted")
    print(f"Field counts: {json.dumps(summary['field_extraction_counts'], indent=2)}")


if __name__ == "__main__":
    main()
