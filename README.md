# Steel Property Predictor — Composition-Based Modeling of Martensitic Alloy Steels

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code License: Apache 2.0](https://img.shields.io/badge/code-Apache%202.0-blue.svg)](LICENSE)
[![Data License: CC BY 4.0](https://img.shields.io/badge/data%20%26%20model-CC%20BY%204.0-lightgrey.svg)](data/LICENSE)
[![Model Version](https://img.shields.io/badge/model-v2.0.0-green.svg)](models/model_summary.json)

**Predicts the mechanical and wear properties of high-carbon martensitic tool and cutlery steels directly from chemical composition, combining machine learning with physics-based metallurgical models trained on standardized laboratory test data.**

134 alloys characterized across four property axes — wear resistance, impact toughness, corrosion resistance, and machinability — powered by CATRA wear measurements, Charpy impact data, and carbide-partition chemistry.

**Interactive web tool — coming soon.** This repository is the open-source model, data, and methodology.

---

## How It Works

Most steel comparisons rely on one person's subjective opinions. This project is different — every property is derived from **objective laboratory measurements** and first-principles metallurgy:

| Property | Method | Data Source |
|----------|--------|-------------|
| Edge Retention | XGBoost + RF + Ridge ensemble | 48 CATRA TCC machine tests |
| Toughness | Physics model + Ridge regression | 12 Charpy impact measurements |
| Corrosion | Matrix Cr + PREN calculation | First-principles metallurgy |
| Ease of Sharpening | CVF + carbide hardness model | Materials science (abrasion theory) |

The models predict base material properties on a 1–10 scale, then combine them with weighting profiles that reflect how different applications trade off those properties:

```
EDC:       35% corrosion + 30% edge retention + 20% toughness + 15% sharpening
Hard Use:  50% toughness + 20% edge retention + 20% sharpening + 10% corrosion
Kitchen:   35% corrosion + 30% edge retention + 25% sharpening + 10% toughness
Bushcraft: 45% toughness + 25% corrosion + 15% edge retention + 15% sharpening
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│   RAW DATA                                                  │
│   Manufacturer PDFs (Crucible, Bohler, Carpenter, Hitachi)  │
│   Academic papers (CATRA tests, Charpy measurements)        │
│   → Compiled & normalized; every source cited in            │
│     DATA_SOURCES.md (raw extractions kept private)          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│   FEATURE ENGINEERING                                       │
│   11 composition elements + 1 PM flag + 12 derived features │
│                                                             │
│   Derived: CVF, matrix Cr, PREN, Ms temp, VC fraction,     │
│   carbide former total, Cr/C ratio, PM interactions         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│   MODELS                                                    │
│                                                             │
│   Edge Retention ─── XGBoost + RF + Ridge (0.45/0.30/0.25) │
│                      trained on CATRA TCC mm                │
│                      LOOCV MAE: 34.8mm (0.39 on 1-10)      │
│                                                             │
│   Toughness ──────── Ridge on physics features              │
│                      calibrated on Charpy ft-lbs            │
│                      Correlation: 0.96 (n=12)               │
│                                                             │
│   Corrosion ──────── Deterministic physics formula          │
│                      Matrix Cr + PREN + N contribution      │
│                      Validation r=0.89 vs KSN (n=61)        │
│                                                             │
│   Sharpening ─────── CVF + VC hardness (deterministic)      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│   OUTPUT                                                    │
│   Per-steel: 4 base scores + 4 use-case scores (1-10)      │
│   → data/processed/all_predictions.csv (134 steels)         │
│   → models/model_weights.json (serialized for inference)    │
└─────────────────────────────────────────────────────────────┘
```

## Sample Output

**Top steels by use case:**

| Steel | Tough | Edge | Corr | Sharp | EDC | Hard Use | Kitchen | Bushcraft |
|-------|-------|------|------|-------|-----|----------|---------|-----------|
| CPM MagnaCut | 5.3 | 4.3 | 8.9 | 6.1 | 6.4 | 5.5 | 6.6 | 6.1 |
| Vanax | 5.1 | 4.1 | 10.0 | 8.0 | 7.0 | 6.0 | 7.2 | 6.6 |
| CPM 3V | 8.0 | 3.4 | 2.9 | 5.5 | 4.5 | 6.1 | 4.2 | 5.7 |
| CPM S35VN | 4.1 | 3.9 | 7.1 | 5.9 | 5.5 | 4.9 | 5.8 | 5.3 |
| M390 | 2.6 | 4.5 | 7.2 | 4.4 | 5.1 | 3.9 | 5.4 | 4.4 |

*Full results for all 134 steels in [`data/processed/all_predictions.csv`](data/processed/all_predictions.csv)*

## Quick Start

```bash
# Clone the repo
git clone https://github.com/Steel-predictor-project/Steel-predictor.git
cd steel-predictor

# Reproduce the model in one command (installs deps + runs the pipeline)
./run_training.sh

# ...or run the steps manually:
pip install -r requirements.txt
python scripts/train_model_v2.py   # trains from data/processed/training_ready.csv
```

Reproduces the published metrics exactly (edge-retention LOOCV MAE 0.391 on 48 CATRA steels, toughness r=0.96, corrosion r=0.89). The corrosion *validation* step compares against KnifeSteelNerds ratings, which are an external reference kept private (see [DATA_SOURCES.md](DATA_SOURCES.md)); it is skipped automatically when that data is absent, and the model's corrosion predictions (physics-based) reproduce regardless.

**Output:**
- `data/processed/all_predictions.csv` — scores for all 134 steels
- `models/model_weights.json` — serialized model for web inference
- `models/model_summary.json` — metrics and methodology summary

### Requirements

- Python 3.10+
- scikit-learn ≥ 1.4
- XGBoost ≥ 2.0
- pandas ≥ 2.1
- numpy ≥ 1.26

## Data Sources

### Primary Measurement Data

| Source | What | Steels |
|--------|------|--------|
| [Larrin Thomas, CATRA TCC Testing (2020)](https://knifesteelnerds.com/2020/05/01/testing-the-edge-retention-of-48-knife-steels/) | Edge retention machine measurements (mm of cardstock cut) | 48 |
| Charpy impact testing (various) | Toughness in ft-lbs at room temperature | 12 |

### Composition Data

| Manufacturer | Steels | Format |
|--------------|--------|--------|
| Crucible Industries (CPM) | 18 | Technical data sheets |
| Bohler-Uddeholm | 16 | Product brochures + pocket book |
| Carpenter Technology | 6 | Technical data sheets |
| Hitachi Metals / Proterial | 15 | Product specifications |
| Alleima (Sandvik) | 5 | Technical data sheets |
| Other / compiled | 14 | Academic papers, manufacturer sites |

### Reference Ratings (for validation only)

- [KnifeSteelNerds](https://knifesteelnerds.com/) ratings used as a reference benchmark (not training target)
- Our model is methodologically independent — trained on machine measurements, not subjective ratings

## Project Structure

```
steel-predictor/
├── scripts/
│   ├── train_model_v2.py      # Training pipeline (CATRA + Charpy + physics)
│   └── normalize_data.py      # Data preprocessing
├── data/
│   ├── processed/             # Normalized compilation + pipeline outputs
│   │   ├── all_predictions.csv
│   │   ├── training_ready.csv
│   │   └── unified_steels.json
│   └── LICENSE                # CC BY 4.0 (data + model)
├── models/
│   ├── model_weights.json     # Full serialized model (~27K lines)
│   ├── model_summary.json     # Metrics + methodology
│   └── xgb_catra_edge_retention.json  # Edge-retention ensemble (XGBoost)
├── scrapers/                  # PDF extraction scripts
├── docs/                      # GitHub Pages site
└── requirements.txt
```

## Key Innovations

1. **CATRA-trained edge retention** — First open-source model using standardized machine cutting tests instead of subjective ratings
2. **Carbide partition chemistry** — Corrosion model accounts for V/Nb/W/Mo consuming carbon before Cr, preserving matrix chromium (critical for high-vanadium steels like S90V)
3. **PM processing interactions** — Models capture how powder metallurgy changes both toughness (finer carbides → less crack initiation) and corrosion (less Cr depletion at grain boundaries)
4. **Application-weighted scoring** — Output layer that weights the base properties differently per application profile rather than collapsing everything into a single "best steel" ranking

## Contributing

Contributions welcome! Areas where help is needed:

- **More CATRA data** — Additional edge retention machine measurements improve the ML model
- **Charpy data for conventional steels** — Current toughness calibration is PM-only
- **Heat treatment sensitivity** — How do different HT parameters affect the same steel?
- **International steels** — Coverage of Chinese (e.g., SG2, VG-XTAL), Swedish (RWL-34), and German steels

### How to contribute data

1. Fork the repo
2. Open an issue or PR adding your steel data **with a public source citation** (datasheet or published measurement). Raw source extractions are curated separately — see `DATA_SOURCES.md` for the sourcing standard.
3. New data is normalized into `data/processed/` and the pipeline (`scripts/train_model_v2.py`) is re-run to validate.
4. All contributed sources are added to `DATA_SOURCES.md`.

## License

This project uses two licenses:

- **Code** — [Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)).
- **Curated data & trained model** — [Creative Commons Attribution 4.0 (CC BY 4.0)](data/LICENSE).

**Attribution is required** for reuse of the data or model: credit "Steel Property Predictor Project" with a link to this repository. These licenses cover only this project's own code, normalized compilation, derived features, and trained model. The underlying factual source data (compositions and lab measurements) is compiled from the third-party sources cited in [DATA_SOURCES.md](DATA_SOURCES.md) and remains the property of its respective publishers.

## Links

- **Interactive web tool:** coming soon
- **Methodology deep-dive:** [docs/methodology.md](docs/methodology.md)
- **Project page:** [steel-predictor-project.github.io/Steel-predictor](https://steel-predictor-project.github.io/Steel-predictor)

---

*An open-source research project. If this helped you understand or choose a steel, consider starring the repo.*
