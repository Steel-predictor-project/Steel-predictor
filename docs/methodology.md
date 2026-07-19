# Methodology

This document describes the models, data, and validation behind Steel Picker's predictions.

---

## Overview

Steel Picker predicts four base properties (edge retention, toughness, corrosion resistance, ease of sharpening) from a steel's chemical composition + processing method, then combines them into use-case scores. Each property uses a different modeling approach chosen for the available data:

| Property | Approach | Training Data | Why This Approach |
|----------|----------|---------------|-------------------|
| Edge Retention | ML ensemble (XGBoost + RF + Ridge) | 48 CATRA TCC tests | Sufficient data for ML; non-linear interactions between elements |
| Toughness | Physics-informed Ridge regression | 12 Charpy measurements | Too few samples for pure ML; physics features capture carbide mechanics |
| Corrosion | Deterministic calculation | None (validated against 61 KSN ratings) | Well-understood first-principles chemistry |
| Ease of Sharpening | Deterministic calculation | None | Direct function of carbide volume and hardness |

---

## 1. Edge Retention

### Data: CATRA TCC Testing

The model is trained on 48 steels tested with a **CATRA (Cutlery and Allied Trades Research Association) TCC (Total Card Cut)** machine — an objective, standardized edge retention test that measures how many millimeters of silica-impregnated cardstock a blade can cut before dulling.

Source: Larrin Thomas, "Testing the Edge Retention of 48 Knife Steels" (2020), published on KnifeSteelNerds.com.

**Test conditions:** 30° inclusive edge angle (15° per side), 400 grit CBN finish, 50N load.

**Range observed:** 271mm (worst, simple carbon steels) to 1009mm (best, Rex 121 — high-V/W tool steel).

### Features (24 total)

```
Composition (11):  C, Cr, V, Mo, W, Co, N, Mn, Si, Nb, Ni
Process (1):       powder_metallurgy (binary)
Derived (12):      total_carbide_formers, cr_to_c_ratio, is_stainless,
                   total_alloy_content, pren, cvf, c_above_eutectoid,
                   vc_fraction, matrix_cr, ms_temp, pm_x_cvf, pm_x_excess_c
```

Key derived features:
- **CVF (Carbide Volume Fraction):** Estimated total volume of hard carbides in the matrix — the primary driver of edge retention
- **vc_fraction:** Volume fraction specifically of vanadium carbides (the hardest common carbide at 2800 HV)
- **pm_x_cvf:** Interaction term — PM processing makes high-CVF steels retain more edge (finer, more evenly distributed carbides)

### Model Architecture

Three-model ensemble with fixed weights:

```
prediction = 0.45 × XGBoost + 0.30 × RandomForest + 0.25 × Ridge
```

**XGBoost hyperparameters** (tuned for small dataset):
- `max_depth=3` (shallow to prevent overfitting)
- `n_estimators=200`
- `learning_rate=0.05`
- `min_child_weight=2`
- `reg_alpha=0.5, reg_lambda=2.0` (strong regularization)
- `subsample=0.8, colsample_bytree=0.8`

**RandomForest:** 200 trees, max_depth=5, min_samples_leaf=3

**Ridge:** alpha=2.0, features standardized (zero-mean, unit-variance)

### Output Normalization

CATRA TCC mm → 1–10 scale (linear mapping):
```
score = 1.0 + 9.0 × (catra_mm - 250) / (1050 - 250)
```

### Validation: Leave-One-Out Cross-Validation

With only 48 training samples, we use LOOCV (train on 47, predict the held-out steel, repeat 48 times):

| Metric | Value |
|--------|-------|
| LOOCV MAE (mm) | 34.8 mm |
| LOOCV MAE (1-10 scale) | 0.391 |
| LOOCV RMSE (mm) | ~45 mm |

The model predicts edge retention within 0.39 points on a 10-point scale — well under the 1.0 target.

### Feature Importance (XGBoost)

| Feature | Importance |
|---------|-----------|
| vc_fraction | 0.406 |
| cvf | 0.265 |
| V | 0.112 |
| C | 0.097 |
| total_carbide_formers | 0.028 |
| total_alloy_content | 0.023 |

VC fraction alone explains 40% of edge retention variance — this aligns with materials science (vanadium carbides are the hardest common carbide and directly resist edge deformation).

---

## 2. Toughness

### Data: Charpy Impact Testing

Calibrated on 12 steels with Charpy V-notch impact testing data (ft-lbs at room temperature). All calibration samples are PM steels tested at typical knife hardness (58-64 HRC).

### Physics-Informed Features

Instead of raw composition, the toughness model uses **metallurgically meaningful derived features**:

```python
features = [
    vc_vol,           # Volume of round, coherent VC carbides (mild toughness penalty)
    cr_carbide_vol,   # Volume of angular Cr7C3 carbides (severe penalty)
    other_carbide_vol,# W/Mo/Nb carbides
    pm,               # Powder metallurgy flag
    pm_tool,          # PM × tool-steel interaction (PM + low-Cr)
    stainless_x_cvf,  # Stainless × total CVF interaction (worst combo for toughness)
    ni,               # Nickel (austenite stabilizer, toughness enhancer)
    eutectoid_c,      # Carbon above eutectoid in non-PM carbon steels
]
```

**Key insight:** Carbide **type** matters more than total volume:
- VC (vanadium carbide): round morphology, coherent interface with matrix → mild toughness penalty
- Cr7C3 (chromium carbide): angular, incoherent interface → severe crack initiation sites
- PM processing: refines all carbides, reducing stress concentrators → significant boost

### Model

Ridge regression (alpha=5.0) trained on the 8 physics features after standardization.

**Calibration results:**

| Metric | Value |
|--------|-------|
| Calibration MAE | 0.683 (on 1-10 scale) |
| Correlation vs Charpy | 0.96 |
| Training samples | 12 |

### Ridge Coefficients

| Feature | Coefficient | Interpretation |
|---------|------------|----------------|
| vc_vol | -0.84 | VC hurts toughness, but less than Cr carbides |
| stainless_x_cvf | -0.85 | Stainless + high carbides = worst combo |
| pm_tool | +0.58 | PM greatly helps tool steels |
| crc_vol | -0.30 | Cr7C3 carbides hurt toughness |
| Intercept | 6.11 | Baseline toughness score |

### Conventional Steel Penalty

All Charpy calibration data is from PM steels. For conventional steels, a processing penalty is applied:
- Standard conventional: -1.5 points
- High-Cr conventional tool steel (D2-type): -2.0 points
- Carbon steel above eutectoid (1095-type): -1.0 point

This reflects the coarser carbide distribution in conventional processing (longer diffusion distances, larger primary carbides).

### Output Normalization

Charpy ft-lbs → 1–10 scale (log scale, since toughness range spans ~5–115 ft-lbs):
```
score = 1.0 + 9.0 × (ln(charpy) - ln(3)) / (ln(130) - ln(3))
```

---

## 3. Corrosion Resistance

### Approach: First-Principles Chemistry

Corrosion resistance is calculated deterministically from **effective matrix chromium** — the amount of Cr actually dissolved in the steel matrix (available to form the protective passive layer), after accounting for Cr consumed by carbide formation.

### Carbide Partition Chemistry

The key insight: not all Cr in the composition contributes to corrosion resistance. Carbon reacts with various elements to form carbides, and the **priority order** determines how much Cr is left:

```
1. V binds C first:  1% V consumes 0.236% C (forms VC)
2. Nb binds next:    1% Nb consumes 0.129% C (forms NbC)
3. W binds next:     1% W consumes 0.065% C (forms M6C)
4. Mo binds next:    1% Mo consumes 0.063% C (forms Mo2C)
5. Remaining C binds Cr: 1% C consumes ~4% Cr (forms Cr7C3)
```

**Example — CPM S90V (2.3C, 14Cr, 9V):**
- V consumes: 9 × 0.236 = 2.12% C → only 0.18% C remains for Cr
- Remaining C consumes: 0.18 × 4 = 0.72% Cr
- Effective matrix Cr: 14 - 0.72 = **13.28%** (still stainless!)

Without this partition chemistry, you'd naively say "2.3% C will consume tons of Cr" — but V scavenges the carbon first.

### PM Processing Bonus

PM steels get a 15% reduction in Cr depletion. Rationale: finer carbide distribution means shorter diffusion distances, so less Cr migrates to grain boundaries during heat treatment.

### Scoring Tiers

| Matrix Cr Range | Score Range | Category |
|-----------------|-------------|----------|
| < 5% | 0–1.5 | Non-stainless (carbon/tool steels) |
| 5–10.5% | 1.5–5.5 | Semi-stainless (D2 territory) |
| 10.5–13% | 5.0–8.5 | Marginally stainless |
| 13–18% | 7.5–9.5 | Solidly stainless |
| > 18% | 9.0–10.0 | Super-stainless (Vanax, LC200N) |

Additional bonuses: nitrogen content (+PREN contribution), Nb (passive film stabilization).

### Validation

| Metric | Value |
|--------|-------|
| MAE vs KSN ratings | 1.362 |
| Correlation vs KSN | 0.888 |
| Validation set | 61 steels |

The higher MAE compared to edge retention is expected — corrosion resistance is partially subjective (depends on environment, maintenance) and our physics model makes different assumptions than KSN's ratings. The 0.89 correlation confirms we're capturing the same underlying signal.

---

## 4. Ease of Sharpening

### Approach: Carbide Hardness Model

Sharpening difficulty is dominated by the hardness of carbides in the steel relative to sharpening media:

| Carbide Type | Hardness (HV) | vs Alumina Stone (2100 HV) |
|--------------|---------------|----------------------------|
| Vanadium carbide (VC) | 2800 | Harder — resists abrasion |
| Tungsten carbide (WC) | 2400 | Harder — resists abrasion |
| Chromium carbide (Cr7C3) | 1650 | Softer — removed normally |

### Formula

```
score = 10.0 - cvf_penalty - vc_penalty - wc_penalty

where:
  cvf_penalty = min(5.5, (CVF / 8.0)^1.3)     # Total carbide volume
  vc_penalty  = V × 0.5 + max(0, V - 2.0) × 0.3  # Vanadium extra penalty above 2%
  wc_penalty  = W × 0.15                        # Tungsten carbide penalty
```

**Interpretation:** A steel with 2% V and moderate CVF scores ~7.5 (easy on normal stones). A steel with 9% V (like S90V) scores ~3.0 (requires diamond or CBN stones).

---

## 5. Use-Case Scoring

### Weights

Each use case applies different importance to the four base properties:

| Use Case | Edge Ret. | Corrosion | Toughness | Sharpening | Rationale |
|----------|-----------|-----------|-----------|------------|-----------|
| **EDC** | 0.30 | 0.35 | 0.20 | 0.15 | Pocket carry = sweat/humidity exposure; moderate cutting tasks |
| **Hard Use** | 0.20 | 0.10 | 0.50 | 0.20 | Batoning, prying, chopping — edge must not chip |
| **Kitchen** | 0.30 | 0.35 | 0.10 | 0.25 | Acidic foods, frequent washing; regular maintenance expected |
| **Bushcraft** | 0.15 | 0.25 | 0.45 | 0.15 | Outdoor exposure + impact tasks; field sharpening less critical |

### Score Calculation

```
use_case_score = Σ (weight_i × property_i)  # clamped to [0.5, 10.0]
```

---

## Validation Metrics Summary

| Model | Metric | Value | Notes |
|-------|--------|-------|-------|
| Edge Retention | LOOCV MAE | 0.391 / 10 | ML trained on CATRA |
| Toughness | Calibration MAE | 0.683 / 10 | Physics + Charpy |
| Toughness | Charpy correlation | 0.96 | n=12 |
| Corrosion | Validation MAE | 1.362 / 10 | Physics vs KSN |
| Corrosion | KSN correlation | 0.888 | n=61 |

---

## Known Limitations

1. **Edge retention training set is from one lab** — All 48 CATRA tests were performed by Larrin Thomas under consistent conditions. Different test protocols (edge angle, abrasive, load) could yield different rankings.

2. **Toughness calibration is PM-only** — The 12 Charpy steels are all powder metallurgy. Conventional steel toughness relies on an empirical penalty (-1.0 to -2.0 points) rather than direct measurement.

3. **Heat treatment is not modeled** — The model assumes "typical knife heat treatment" for each steel. A poorly heat-treated S35VN will perform worse than predicted; an optimally treated one may exceed predictions.

4. **No hardness input** — HRC is not used as a feature. In reality, the same steel at 58 HRC vs 64 HRC has significantly different edge retention and toughness.

5. **Corrosion is environment-independent** — Real corrosion depends on exposure (saltwater vs dry carry vs food acids). Our score represents intrinsic resistance, not a specific environment.

6. **Small training set** — 48 steels for edge retention is enough for tree ensembles but limits detection of rare interactions (e.g., Co+W synergies in HSS steels).

7. **Bias toward popular steels** — The training set over-represents Crucible CPM steels and under-represents Chinese and budget steels.

---

## Future Work

- **More CATRA data:** Each additional steel tested on CATRA directly improves the ML model. Target: 80+ steels.
- **Charpy expansion:** Test conventional steels to eliminate the penalty heuristic.
- **Heat treatment sensitivity:** Model how austenitizing temperature and tempering affect predictions.
- **HRC as input:** Allow users to specify target hardness for more accurate predictions.
- **Wear mechanism differentiation:** CATRA measures slicing; separate model for push-cutting and rope-cutting.
- **Confidence intervals:** Bootstrap prediction intervals to communicate uncertainty.
- **Edge stability (chipping resistance):** Separate metric from overall toughness, relevant for thin-geometry blades.

---

## References

1. Thomas, L. (2020). "Testing the Edge Retention of 48 Knife Steels." KnifeSteelNerds.com. [Link](https://knifesteelnerds.com/2020/05/01/testing-the-edge-retention-of-48-knife-steels/)
2. Crucible Industries. CPM Steel Technical Data Series. [crucible.com](https://www.crucible.com)
3. Bohler-Uddeholm. Steel Pocket Book & Knife Steel Brochure.
4. Thomas, L. "Knife Steel Nerds Ratings." KnifeSteelNerds.com (used as validation reference only).
5. ASTM E23 — Standard Test Methods for Notched Bar Impact Testing of Metallic Materials.
6. CATRA — Cutlery and Allied Trades Research Association, Sheffield, UK. TCC Test Standard.
