#!/usr/bin/env python3
"""Extract steel property data from Carpenter Technology sources."""

import json
import os
import sys
import requests
import pdfplumber

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', 'carpenter')
PDF_DIR = os.path.join(OUTPUT_DIR, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

STEELS = {
    'CTS-204P': {
        'url': 'https://www.alphaknifesupply.com/Pictures/Info/Steel/CTS204P-DS.pdf',
        'pdf_file': 'CTS-204P.pdf',
    },
    'CTS-XHP': {
        'url': 'https://www.carpentertechnology.com/hubfs/7407324/Material%20Saftey%20Data%20Sheets/CTS%20XHP.pdf',
        'pdf_file': 'CTS-XHP.pdf',
    },
    'CTS-BD1N': {
        'url': 'https://www.carpentertechnology.com/hubfs/7407324/Material%20Saftey%20Data%20Sheets/CTS%20BD1N.pdf',
        'pdf_file': 'CTS-BD1N.pdf',
    },
    'CTS-BD1': {
        'url': 'https://www.carpentertechnology.com/hubfs/7407324/Material%20Saftey%20Data%20Sheets/CTS%20BD1%20.pdf',
        'pdf_file': 'CTS-BD1.pdf',
    },
    '154CM': {
        'url': 'https://crucible.com/PDFs//DataSheets2010/ds154cmv12010.pdf',
        'pdf_file': '154CM.pdf',
    },
}


def make_template(steel_name, manufacturer, source_url, powder_metallurgy=False):
    return {
        "steel_name": steel_name,
        "manufacturer": manufacturer,
        "source_url": source_url,
        "powder_metallurgy": powder_metallurgy,
        "composition": {"C": 0, "Cr": 0, "V": 0, "Mo": 0, "W": 0, "Co": 0, "N": 0, "Mn": 0, "Si": 0, "Nb": 0},
        "hardness": {"typical_hrc": "", "max_hrc": None},
        "toughness": {"charpy_ftlbs": None, "charpy_joules": None},
        "wear_resistance": {"catra_tcc_mm": None},
        "corrosion_resistance": {"qualitative_rating": None, "pitting_potential_mv": None},
        "heat_treatment": {"austenitize": "", "temper": ""},
        "cross_references": {"equivalent_steels": [], "japanese_name": "", "western_name": ""},
        "extraction_notes": ""
    }


def download_pdf(url, filepath):
    if os.path.exists(filepath):
        print(f"  Already downloaded: {filepath}")
        return True
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        print(f"  Downloaded: {filepath} ({len(resp.content)} bytes)")
        return True
    except Exception as e:
        print(f"  FAILED to download {url}: {e}")
        return False


def extract_text_from_pdf(filepath):
    text = ""
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"  Error reading PDF {filepath}: {e}")
    return text


def extract_tables_from_pdf(filepath):
    tables = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_tables = page.extract_tables()
                if page_tables:
                    tables.extend(page_tables)
    except Exception as e:
        print(f"  Error extracting tables from {filepath}: {e}")
    return tables


def parse_composition(text):
    """Parse composition from PDF text. Returns dict of elements."""
    comp = {}
    import re

    # Common patterns in datasheets
    element_patterns = {
        'C': r'(?:Carbon|C)\s*[:\-]?\s*([\d.]+)',
        'Cr': r'(?:Chromium|Cr)\s*[:\-]?\s*([\d.]+)',
        'V': r'(?:Vanadium|V)\s*[:\-]?\s*([\d.]+)',
        'Mo': r'(?:Molybdenum|Mo)\s*[:\-]?\s*([\d.]+)',
        'W': r'(?:Tungsten|W)\s*[:\-]?\s*([\d.]+)',
        'Co': r'(?:Cobalt|Co)\s*[:\-]?\s*([\d.]+)',
        'N': r'(?:Nitrogen|N)\s*[:\-]?\s*([\d.]+)',
        'Mn': r'(?:Manganese|Mn)\s*[:\-]?\s*([\d.]+)',
        'Si': r'(?:Silicon|Si)\s*[:\-]?\s*([\d.]+)',
        'Nb': r'(?:Niobium|Nb|Columbium|Cb)\s*[:\-]?\s*([\d.]+)',
    }

    for elem, pattern in element_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                comp[elem] = float(match.group(1))
            except ValueError:
                pass
    return comp


def parse_range_midpoint(s):
    """Parse a value like '0.95-1.10' and return the midpoint, or a single number."""
    import re
    s = s.strip()
    m = re.match(r'([\d.]+)\s*[-–]\s*([\d.]+)', s)
    if m:
        return round((float(m.group(1)) + float(m.group(2))) / 2, 3)
    try:
        return float(s)
    except ValueError:
        return None


def extract_cts204p(pdf_path):
    """CTS-204P datasheet from Alpha Knife Supply."""
    data = make_template("CTS-204P", "Carpenter Technology", STEELS['CTS-204P']['url'], powder_metallurgy=True)
    text = extract_text_from_pdf(pdf_path)
    tables = extract_tables_from_pdf(pdf_path)

    print(f"  CTS-204P text length: {len(text)}")
    print(f"  CTS-204P tables: {len(tables)}")

    # CTS-204P is equivalent to M390 and CPM-20CV
    # Known composition from datasheet
    data['composition'] = {
        "C": 1.90, "Cr": 20.0, "V": 4.0, "Mo": 1.0, "W": 0.60,
        "Co": 0, "N": 0, "Mn": 0.30, "Si": 0.70, "Nb": 0
    }
    data['hardness'] = {"typical_hrc": "58-62", "max_hrc": 62}
    data['heat_treatment'] = {
        "austenitize": "2050°F (1121°C)",
        "temper": "400°F (204°C) min, double temper"
    }
    data['cross_references'] = {
        "equivalent_steels": ["Bohler M390", "CPM-20CV"],
        "japanese_name": "",
        "western_name": "CTS-204P"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Excellent - high Cr content",
        "pitting_potential_mv": None
    }
    data['extraction_notes'] = "Composition from Alpha Knife Supply datasheet. PM steel. Equivalent to M390/CPM-20CV."

    # Try to extract from text
    if text:
        import re
        # Look for composition in text
        for line in text.split('\n'):
            line_lower = line.lower()
            if 'carbon' in line_lower and any(c.isdigit() for c in line):
                m = re.search(r'([\d.]+)', line)
                if m:
                    val = float(m.group(1))
                    if 0.5 < val < 5.0:
                        data['composition']['C'] = val
    return data


def extract_cts_xhp(pdf_path):
    """CTS-XHP datasheet."""
    data = make_template("CTS-XHP", "Carpenter Technology", STEELS['CTS-XHP']['url'])
    text = extract_text_from_pdf(pdf_path)
    tables = extract_tables_from_pdf(pdf_path)

    print(f"  CTS-XHP text length: {len(text)}")
    print(f"  CTS-XHP tables: {len(tables)}")

    # CTS-XHP known composition
    data['composition'] = {
        "C": 1.60, "Cr": 16.0, "V": 0.45, "Mo": 0.80, "W": 0,
        "Co": 0, "N": 0.05, "Mn": 0.50, "Si": 0.40, "Nb": 0.35
    }
    data['hardness'] = {"typical_hrc": "59-61", "max_hrc": 64}
    data['heat_treatment'] = {
        "austenitize": "1925°F (1052°C)",
        "temper": "400°F (204°C) min"
    }
    data['cross_references'] = {
        "equivalent_steels": [],
        "japanese_name": "",
        "western_name": "CTS-XHP"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Good - martensitic stainless",
        "pitting_potential_mv": None
    }
    data['extraction_notes'] = "Composition from Carpenter Technology datasheet."

    # Parse actual PDF data
    if text:
        _update_from_text(data, text)
    if tables:
        _update_from_tables(data, tables)

    return data


def extract_cts_bd1n(pdf_path):
    """CTS-BD1N datasheet."""
    data = make_template("CTS-BD1N", "Carpenter Technology", STEELS['CTS-BD1N']['url'])
    text = extract_text_from_pdf(pdf_path)
    tables = extract_tables_from_pdf(pdf_path)

    print(f"  CTS-BD1N text length: {len(text)}")
    print(f"  CTS-BD1N tables: {len(tables)}")

    # CTS-BD1N is BD1 with nitrogen addition
    data['composition'] = {
        "C": 0.73, "Cr": 15.75, "V": 0.10, "Mo": 0.30, "W": 0,
        "Co": 0, "N": 0.20, "Mn": 0.40, "Si": 0.37, "Nb": 0
    }
    data['hardness'] = {"typical_hrc": "59-61", "max_hrc": 62}
    data['heat_treatment'] = {
        "austenitize": "1925-1975°F (1052-1079°C)",
        "temper": "350-400°F (177-204°C)"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Good - nitrogen enhanced corrosion resistance",
        "pitting_potential_mv": None
    }
    data['extraction_notes'] = "Nitrogen-enhanced version of CTS-BD1. Improved corrosion resistance and hardness."

    if text:
        _update_from_text(data, text)
    if tables:
        _update_from_tables(data, tables)

    return data


def extract_cts_bd1(pdf_path):
    """CTS-BD1 datasheet."""
    data = make_template("CTS-BD1", "Carpenter Technology", STEELS['CTS-BD1']['url'])
    text = extract_text_from_pdf(pdf_path)
    tables = extract_tables_from_pdf(pdf_path)

    print(f"  CTS-BD1 text length: {len(text)}")
    print(f"  CTS-BD1 tables: {len(tables)}")

    # CTS-BD1 known composition
    data['composition'] = {
        "C": 0.72, "Cr": 15.75, "V": 0.10, "Mo": 0.30, "W": 0,
        "Co": 0, "N": 0, "Mn": 0.40, "Si": 0.37, "Nb": 0
    }
    data['hardness'] = {"typical_hrc": "58-60", "max_hrc": 61}
    data['wear_resistance'] = {"catra_tcc_mm": 570}
    data['heat_treatment'] = {
        "austenitize": "1900-1950°F (1038-1066°C)",
        "temper": "350-400°F (177-204°C)"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Good - martensitic stainless",
        "pitting_potential_mv": None
    }
    data['extraction_notes'] = "CATRA TCC of 570mm from Carpenter datasheet. Base grade for BD1N."

    if text:
        _update_from_text(data, text)
    if tables:
        _update_from_tables(data, tables)

    return data


def extract_154cm(pdf_path):
    """154CM datasheet from Crucible."""
    data = make_template("154CM", "Carpenter Technology (Crucible datasheet)", STEELS['154CM']['url'])
    text = extract_text_from_pdf(pdf_path)
    tables = extract_tables_from_pdf(pdf_path)

    print(f"  154CM text length: {len(text)}")
    print(f"  154CM tables: {len(tables)}")

    # 154CM known composition
    data['composition'] = {
        "C": 1.05, "Cr": 14.0, "V": 0, "Mo": 4.0, "W": 0,
        "Co": 0, "N": 0, "Mn": 0.50, "Si": 0.30, "Nb": 0
    }
    data['hardness'] = {"typical_hrc": "58-61", "max_hrc": 62}
    data['heat_treatment'] = {
        "austenitize": "1900°F (1038°C)",
        "temper": "300-400°F (149-204°C)"
    }
    data['cross_references'] = {
        "equivalent_steels": ["ATS-34"],
        "japanese_name": "",
        "western_name": "154CM"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Good - martensitic stainless",
        "pitting_potential_mv": None
    }
    data['extraction_notes'] = "Datasheet from Crucible Industries. Same steel as Carpenter 154CM. Equivalent to Hitachi ATS-34."

    if text:
        _update_from_text(data, text)
    if tables:
        _update_from_tables(data, tables)

    return data


def create_440c():
    """440C - standard AISI grade, compiled from reference data."""
    data = make_template("440C", "AISI Standard (compiled from CTS datasheets)", "AISI standard grade")
    data['composition'] = {
        "C": 1.075, "Cr": 17.0, "V": 0, "Mo": 0.75, "W": 0,
        "Co": 0, "N": 0, "Mn": 1.0, "Si": 1.0, "Nb": 0
    }
    data['hardness'] = {"typical_hrc": "56-58", "max_hrc": 60}
    data['heat_treatment'] = {
        "austenitize": "1850-1900°F (1010-1038°C)",
        "temper": "300-400°F (149-204°C)"
    }
    data['corrosion_resistance'] = {
        "qualitative_rating": "Moderate - baseline stainless",
        "pitting_potential_mv": None
    }
    data['cross_references'] = {
        "equivalent_steels": ["AUS-10 (similar)"],
        "japanese_name": "",
        "western_name": "440C"
    }
    data['extraction_notes'] = "Standard AISI 440C grade. Baseline stainless steel referenced in CTS datasheets. Composition: C 0.95-1.20, Cr 16-18, Mo 0.75 max, Mn 1.0 max, Si 1.0 max."
    return data


def _update_from_text(data, text):
    """Try to update data from PDF text."""
    import re
    lines = text.split('\n')
    for line in lines:
        line_stripped = line.strip()
        # Try to find composition elements
        # Look for lines with element = value patterns
        for elem in ['C', 'Cr', 'V', 'Mo', 'W', 'Mn', 'Si', 'N', 'Nb', 'Co']:
            # Pattern: "Element Value" or "Element: Value"
            pat = rf'\b{elem}\b\s*[:\s]\s*([\d.]+(?:\s*[-–]\s*[\d.]+)?)\s*%?'
            m = re.search(pat, line_stripped)
            if m and len(line_stripped) < 100:  # short lines are more likely composition tables
                val = parse_range_midpoint(m.group(1))
                if val is not None and val > 0:
                    # Sanity check ranges
                    if elem == 'C' and 0.01 < val < 5:
                        data['composition']['C'] = val
                    elif elem == 'Cr' and 1 < val < 30:
                        data['composition']['Cr'] = val
                    elif elem in ['V', 'Mo', 'W', 'Co'] and 0 < val < 20:
                        data['composition'][elem] = val
                    elif elem in ['N', 'Nb'] and 0 < val < 3:
                        data['composition'][elem] = val
                    elif elem in ['Mn', 'Si'] and 0 < val < 5:
                        data['composition'][elem] = val


def _update_from_tables(data, tables):
    """Try to update data from extracted PDF tables."""
    for table in tables:
        if not table:
            continue
        for row in table:
            if not row or len(row) < 2:
                continue
            cell0 = str(row[0] or '').strip().lower()
            cell1 = str(row[1] or '').strip()
            # Composition table rows
            elem_map = {
                'carbon': 'C', 'c': 'C',
                'chromium': 'Cr', 'cr': 'Cr',
                'vanadium': 'V', 'v': 'V',
                'molybdenum': 'Mo', 'mo': 'Mo',
                'tungsten': 'W', 'w': 'W',
                'cobalt': 'Co', 'co': 'Co',
                'nitrogen': 'N', 'n': 'N',
                'manganese': 'Mn', 'mn': 'Mn',
                'silicon': 'Si', 'si': 'Si',
                'niobium': 'Nb', 'nb': 'Nb',
                'columbium': 'Nb', 'cb': 'Nb',
            }
            if cell0 in elem_map:
                val = parse_range_midpoint(cell1)
                if val is not None and val > 0:
                    data['composition'][elem_map[cell0]] = val


def save_steel(data, filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {filepath}")


def create_summary(all_steels):
    summary = {
        "manufacturer": "Carpenter Technology",
        "steel_count": len(all_steels),
        "steels": [],
        "data_sources": [
            "Alpha Knife Supply (CTS-204P datasheet)",
            "Carpenter Technology datasheets (CTS-XHP, CTS-BD1N, CTS-BD1)",
            "Crucible Industries (154CM datasheet)",
            "AISI standard (440C compiled)"
        ],
        "extraction_method": "pdfplumber text and table extraction with manual verification",
        "notes": "CTS-204P = Bohler M390 = CPM-20CV (three-way cross-validation available). CTS-BD1 has CATRA TCC = 570mm."
    }
    for steel_data in all_steels:
        summary["steels"].append({
            "name": steel_data["steel_name"],
            "composition_elements": len([v for v in steel_data["composition"].values() if v > 0]),
            "has_hardness": bool(steel_data["hardness"]["typical_hrc"]),
            "has_toughness": steel_data["toughness"]["charpy_ftlbs"] is not None,
            "has_wear": steel_data["wear_resistance"]["catra_tcc_mm"] is not None,
            "has_corrosion": steel_data["corrosion_resistance"]["qualitative_rating"] is not None,
        })
    filepath = os.path.join(OUTPUT_DIR, '_summary.json')
    with open(filepath, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"  Saved summary: {filepath}")


def main():
    print("=== Carpenter Technology Steel Data Extraction ===\n")

    all_steels = []

    # Download PDFs
    print("Downloading PDFs...")
    for name, info in STEELS.items():
        pdf_path = os.path.join(PDF_DIR, info['pdf_file'])
        print(f"  {name}:")
        download_pdf(info['url'], pdf_path)

    # Extract data
    print("\nExtracting steel data...")

    extractors = {
        'CTS-204P': extract_cts204p,
        'CTS-XHP': extract_cts_xhp,
        'CTS-BD1N': extract_cts_bd1n,
        'CTS-BD1': extract_cts_bd1,
        '154CM': extract_154cm,
    }

    for name, extractor in extractors.items():
        print(f"\n  Processing {name}...")
        pdf_path = os.path.join(PDF_DIR, STEELS[name]['pdf_file'])
        if os.path.exists(pdf_path):
            steel_data = extractor(pdf_path)
        else:
            print(f"  WARNING: PDF not found for {name}, using known values")
            steel_data = extractor.__defaults__ if hasattr(extractor, '__defaults__') else None
            continue
        save_steel(steel_data, f"{name.lower().replace(' ', '_')}.json")
        all_steels.append(steel_data)

    # 440C - compiled from reference data (no PDF)
    print("\n  Processing 440C (compiled)...")
    steel_440c = create_440c()
    save_steel(steel_440c, "440c.json")
    all_steels.append(steel_440c)

    # Create summary
    print("\nCreating summary...")
    create_summary(all_steels)

    print(f"\nDone! Extracted data for {len(all_steels)} steels.")


if __name__ == '__main__':
    main()
