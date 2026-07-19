#!/usr/bin/env python3
"""
Steel Property Predictor v2 — Measurement-Based Training Pipeline

Trains models on OBJECTIVE measurements rather than subjective 1-10 ratings:
  - Edge Retention: XGBoost + RF + Ridge trained on CATRA TCC mm (48 steels)
  - Toughness: Physics-informed model calibrated on Charpy ft-lbs (12 steels)
  - Corrosion Resistance: Physics calculation from matrix Cr / PREN (no ML)

Output: use-case scores (EDC, Hard Use, Kitchen, Bushcraft) on a 1-10 scale.

This approach is methodologically distinct from KnifeSteelNerds ratings because:
  1. Edge retention is trained on machine measurements (CATRA), not opinions
  2. Toughness is derived from physics + Charpy data, not subjective scoring
  3. Corrosion is calculated from metallurgy, not rated by a person
  4. Use-case scores are an original output layer with novel weightings
"""

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler
import xgboost as xgb

warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
MODELS_DIR = REPO_ROOT / "models"

# Feature columns (11 composition + 1 PM flag + 12 derived = 24)
COMPOSITION_FEATURES = ["C", "Cr", "V", "Mo", "W", "Co", "N", "Mn", "Si", "Nb", "Ni"]
DERIVED_FEATURES = [
    "total_carbide_formers", "cr_to_c_ratio", "is_stainless", "total_alloy_content",
    "pren", "cvf", "c_above_eutectoid", "vc_fraction",
    "matrix_cr", "ms_temp", "pm_x_cvf", "pm_x_excess_c",
]
PROCESS_FEATURES = ["powder_metallurgy"]
ALL_FEATURES = COMPOSITION_FEATURES + PROCESS_FEATURES + DERIVED_FEATURES

# XGBoost hyperparameters (tuned for small datasets)
XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 2,
    "reg_alpha": 0.5,
    "reg_lambda": 2.0,
    "gamma": 0.1,
    "random_state": 42,
}

RF_PARAMS = {
    "n_estimators": 200,
    "max_depth": 5,
    "min_samples_leaf": 3,
    "max_features": 0.7,
    "random_state": 42,
}

RIDGE_ALPHA = 2.0

# Ensemble weights
XGB_WEIGHT = 0.45
RF_WEIGHT = 0.30
RIDGE_WEIGHT = 0.25

# CATRA TCC → 1-10 scale conversion
# Based on observed range: 271mm (worst) to 1009mm (best, Rex 121)
# Using a slightly compressed range to avoid edge effects
CATRA_MIN = 250.0   # maps to ~1.0
CATRA_MAX = 1050.0  # maps to ~10.0

# Charpy ft-lbs → 1-10 scale (log scale since range is 5-115)
CHARPY_MIN = 3.0    # maps to ~1.0
CHARPY_MAX = 130.0  # maps to ~10.0

# Use-case scoring weights (must sum to 1.0 per use case)
USE_CASE_WEIGHTS = {
    "edc": {
        "edge_retention": 0.30,
        "corrosion_resistance": 0.35,
        "toughness": 0.20,
        "ease_of_sharpening": 0.15,
    },
    "hard_use": {
        "toughness": 0.50,
        "edge_retention": 0.20,
        "corrosion_resistance": 0.10,
        "ease_of_sharpening": 0.20,
    },
    "kitchen": {
        "corrosion_resistance": 0.35,
        "edge_retention": 0.30,
        "ease_of_sharpening": 0.25,
        "toughness": 0.10,
    },
    "bushcraft": {
        "toughness": 0.45,
        "corrosion_resistance": 0.25,
        "edge_retention": 0.15,
        "ease_of_sharpening": 0.15,
    },
}


def load_data():
    """Load the unified steel dataset."""
    csv_path = PROCESSED_DIR / "training_ready.csv"
    df = pd.read_csv(csv_path)
    # Only steels with composition
    mask = df[COMPOSITION_FEATURES].sum(axis=1) > 0
    df = df[mask].copy()
    print(f"Loaded {len(df)} steels with composition data")
    return df


def catra_to_score(catra_mm):
    """Convert CATRA TCC mm to 1-10 scale (linear mapping)."""
    score = 1.0 + 9.0 * (catra_mm - CATRA_MIN) / (CATRA_MAX - CATRA_MIN)
    return np.clip(score, 0.5, 10.5)


def charpy_to_score(charpy_ftlbs):
    """Convert Charpy ft-lbs to 1-10 scale (log scale)."""
    log_val = np.log(np.clip(charpy_ftlbs, CHARPY_MIN, CHARPY_MAX))
    log_min = np.log(CHARPY_MIN)
    log_max = np.log(CHARPY_MAX)
    score = 1.0 + 9.0 * (log_val - log_min) / (log_max - log_min)
    return np.clip(score, 0.5, 10.5)


def compute_effective_matrix_cr(row):
    """
    Calculate effective matrix Cr accounting for carbide partition chemistry.

    Key insight: V preferentially forms VC carbides, consuming C before Cr can.
    In high-V steels (CPM S90V, CPM 10V), most C goes to VC, leaving Cr in matrix.
    Only 'leftover' C after V/Nb/W/Mo bind their share consumes Cr.

    PM processing additionally preserves ~10-15% more Cr in matrix due to
    finer carbide distribution and shorter diffusion distances.
    """
    c = row.get("C", 0)
    cr = row.get("Cr", 0)
    v = row.get("V", 0)
    nb = row.get("Nb", 0)
    mo = row.get("Mo", 0)
    w = row.get("W", 0)
    pm = row.get("powder_metallurgy", 0)

    # Carbon consumed by each carbide former (stoichiometric ratios)
    c_by_v = min(c, v * 0.236)          # VC: 1%V → 0.236%C
    c_remaining = max(0, c - c_by_v)
    c_by_nb = min(c_remaining, nb * 0.129)  # NbC: 1%Nb → 0.129%C
    c_remaining = max(0, c_remaining - c_by_nb)
    c_by_w = min(c_remaining, w * 0.065)    # M6C: 1%W → 0.065%C
    c_remaining = max(0, c_remaining - c_by_w)
    c_by_mo = min(c_remaining, mo * 0.063)  # Mo2C: 1%Mo → 0.063%C
    c_remaining = max(0, c_remaining - c_by_mo)

    # Remaining C forms Cr7C3: each %C consumes ~4% Cr
    cr_consumed = c_remaining * 4.0

    # PM bonus: finer carbides mean ~15% less Cr depletion
    if pm:
        cr_consumed *= 0.85

    effective_cr = max(0, cr - cr_consumed)
    return effective_cr


def compute_corrosion_score(row):
    """
    Physics-based corrosion resistance score from composition.

    Uses effective matrix Cr (accounting for carbide partition chemistry)
    plus PREN and nitrogen contributions.
    """
    matrix_cr = compute_effective_matrix_cr(row)
    pren = row.get("pren", 0)
    n_content = row.get("N", 0)
    nb = row.get("Nb", 0)
    pm = row.get("powder_metallurgy", 0)

    # Nb bonus: scavenges C from Cr (already accounted in matrix_cr)
    # but also stabilizes passive film directly
    nb_bonus = min(0.5, nb * 0.3)

    if matrix_cr < 5.0:
        # Non-stainless: carbon/tool steels
        return min(1.5, row.get("total_alloy_content", 0) * 0.03 + nb_bonus)
    elif matrix_cr < 10.5:
        # Semi-stainless zone (D2, CPM CruWear territory)
        base = 1.5 + 3.5 * (matrix_cr - 5.0) / 5.5
        return min(5.5, base + nb_bonus)
    elif matrix_cr < 13.0:
        # Marginally stainless
        base = 5.0 + 2.5 * (matrix_cr - 10.5) / 2.5
        n_bonus = min(1.0, n_content * 3.0)
        return min(8.5, base + n_bonus + nb_bonus)
    elif matrix_cr < 18.0:
        # Solidly stainless
        base = 7.5 + 1.5 * (matrix_cr - 13.0) / 5.0
        pren_bonus = min(0.5, max(0, (pren - 20)) * 0.03)
        n_bonus = min(0.5, n_content * 2.0)
        return min(9.5, base + pren_bonus + n_bonus + nb_bonus)
    else:
        # Super-stainless (Vanax, H1, LC200N)
        base = 9.0 + 1.0 * min(1.0, (matrix_cr - 18.0) / 5.0)
        n_bonus = min(0.5, n_content * 1.0)
        return min(10.0, base + n_bonus)


def get_toughness_physics_features(row):
    """
    Compute physics-informed features for toughness prediction.

    Key insight from Charpy data: carbide TYPE matters more than total CVF.
    - VC (vanadium carbide): round, coherent interface → mild toughness penalty
    - Cr7C3 (chromium carbide): angular, incoherent → severe penalty
    - PM processing: finer carbides → significant toughness boost
    - Stainless + high CVF: worst combination for toughness
    """
    c = row.get("C", 0)
    cr = row.get("Cr", 0)
    v = row.get("V", 0)
    mo = row.get("Mo", 0)
    w = row.get("W", 0)
    nb = row.get("Nb", 0)
    ni = row.get("Ni", 0)
    pm = row.get("powder_metallurgy", 0)

    # Partition C into carbide types (stoichiometric priority order)
    c_by_v = min(c, v * 0.236)
    c_rem = max(0, c - c_by_v)
    c_by_nb = min(c_rem, nb * 0.129)
    c_rem = max(0, c_rem - c_by_nb)
    c_by_w = min(c_rem, w * 0.065)
    c_rem = max(0, c_rem - c_by_w)
    c_by_mo = min(c_rem, mo * 0.063)
    c_rem = max(0, c_rem - c_by_mo)

    vc_vol = v * 1.95
    cr_carbide_vol = c_rem * 13.5
    other_carbide_vol = (c_by_w + c_by_mo) * 10.0 + nb * 1.8
    total_cvf = vc_vol + cr_carbide_vol + other_carbide_vol + cr * 0.18
    is_stainless = 1 if cr >= 13 else 0

    return np.array([
        vc_vol,
        cr_carbide_vol,
        other_carbide_vol,
        1.0 if pm else 0.0,
        (1.0 if pm else 0.0) * (1.0 if cr < 8.0 else 0.0),  # PM tool interaction
        is_stainless * total_cvf / 10.0,  # stainless-carbide interaction
        ni,
        max(0, c - 0.77) if cr < 3.0 and not pm else 0.0,  # eutectoid penalty
    ])


TOUGHNESS_FEATURE_NAMES = ['vc_vol', 'crc_vol', 'other_vol', 'pm', 'pm_tool',
                            'stainless_x_cvf', 'ni', 'eutectoid_c']

# Pre-calibrated Ridge coefficients (trained on 12 Charpy measurements, alpha=5)
# These are standardized coefficients; applied after z-scoring features
# Scaler mean/std and intercept are set during calibration in calibrate_toughness_model()
TOUGHNESS_RIDGE = None  # set by calibrate_toughness_model()
TOUGHNESS_SCALER = None


def compute_toughness_score(row):
    """
    Toughness score using Ridge regression calibrated on Charpy data.

    For PM steels: uses Ridge model directly (trained on 12 PM steels with Charpy data).
    For conventional steels: applies a conventional penalty (~1.5 points) since
    all calibration data is PM. The penalty represents coarser carbide distribution
    in conventional processing.
    """
    if TOUGHNESS_RIDGE is None:
        # Fallback if not calibrated yet
        return 5.0

    features = get_toughness_physics_features(row).reshape(1, -1)
    features_scaled = TOUGHNESS_SCALER.transform(features)
    score = TOUGHNESS_RIDGE.predict(features_scaled)[0]

    # Conventional penalty: all Charpy data is from PM steels.
    # Conventional processing yields coarser carbides → lower toughness.
    # Empirical: CPM 3V (PM, T=8.0) vs A2 (conv, T=6.5) → ~1.5 point difference
    pm = row.get("powder_metallurgy", 0)
    if not pm:
        cr = row.get("Cr", 0)
        c = row.get("C", 0)
        # Larger penalty for high-Cr conventional tool steels (D2 type)
        if cr > 4.0 and c > 0.8:
            score -= 2.0
        elif c > 0.77 and cr < 3.0:
            # Simple carbon above eutectoid (1095): extra brittleness
            score -= 1.0
        else:
            # Standard conventional steel
            score -= 1.5

    return float(np.clip(score, 0.5, 10.0))


def compute_ease_of_sharpening(row):
    """
    Ease of sharpening score from composition.

    Primary factors (from materials science of abrasion):
    1. Vanadium carbides (VC, 2800 HV) are harder than most sharpening stones
       (alumina ~2100 HV) — they resist abrasion, making steel hard to sharpen
    2. Tungsten carbides (WC, 2400 HV) are similarly problematic
    3. Total carbide volume fraction increases work required
    4. Chromium carbides (Cr7C3, 1650 HV) are softer than stones — mild effect

    Score range: 10 (trivially easy) to 0.5 (requires diamond/CBN)
    """
    cvf = row.get("cvf", 0)
    v = row.get("V", 0)
    w = row.get("W", 0)

    if cvf <= 0:
        cvf = max(1.0, row.get("C", 0) * 13.5 + row.get("Cr", 0) * 0.18)

    # CVF penalty: power-law (mild at low CVF, steep at high)
    # Capped at 5.5 to leave room for V/W penalties
    cvf_penalty = min(5.5, (cvf / 8.0) ** 1.3)

    # VC penalty: dominant factor for "can't sharpen on normal stones"
    # V > 2% makes a steel significantly harder to sharpen
    vc_penalty = v * 0.5 + max(0, v - 2.0) * 0.3

    # WC penalty (tungsten carbides, less common but also very hard)
    wc_penalty = w * 0.15

    score = 10.0 - cvf_penalty - vc_penalty - wc_penalty
    return float(np.clip(score, 0.5, 10.0))


# ═══════════════════════════════════════════════════════════════════
# EDGE RETENTION ML MODEL (trained on CATRA TCC measurements)
# ═══════════════════════════════════════════════════════════════════

def train_edge_retention_model(df):
    """Train ensemble model on CATRA TCC data (objective measurement)."""
    # Filter to steels with CATRA measurements
    catra_df = df[df["catra_tcc_mm"].notna() & (df["catra_tcc_mm"] > 0)].copy()
    print(f"\n  Training edge retention model on {len(catra_df)} steels with CATRA TCC data")

    X = catra_df[ALL_FEATURES].values
    y = catra_df["catra_tcc_mm"].values

    # Add test HRC as feature if available
    feature_names = ALL_FEATURES.copy()

    # LOOCV
    loo = LeaveOneOut()
    predictions = np.zeros(len(y))

    for train_idx, test_idx in loo.split(X):
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr = y[train_idx]

        scaler = StandardScaler()
        X_tr_scaled = scaler.fit_transform(X_tr)
        X_te_scaled = scaler.transform(X_te)

        xgb_model = xgb.XGBRegressor(**XGB_PARAMS)
        xgb_model.fit(X_tr, y_tr, verbose=False)

        rf_model = RandomForestRegressor(**RF_PARAMS)
        rf_model.fit(X_tr, y_tr)

        ridge_model = Ridge(alpha=RIDGE_ALPHA)
        ridge_model.fit(X_tr_scaled, y_tr)

        xgb_pred = xgb_model.predict(X_te)
        rf_pred = rf_model.predict(X_te)
        ridge_pred = ridge_model.predict(X_te_scaled)

        predictions[test_idx] = XGB_WEIGHT * xgb_pred + RF_WEIGHT * rf_pred + RIDGE_WEIGHT * ridge_pred

    # Metrics in mm
    mae_mm = mean_absolute_error(y, predictions)
    rmse_mm = np.sqrt(mean_squared_error(y, predictions))
    # Convert to 1-10 scale for comparison
    y_scores = catra_to_score(y)
    pred_scores = catra_to_score(predictions)
    mae_score = mean_absolute_error(y_scores, pred_scores)

    print(f"  LOOCV MAE: {mae_mm:.1f} mm ({mae_score:.3f} on 1-10 scale)")
    print(f"  LOOCV RMSE: {rmse_mm:.1f} mm")

    # Train final model on all CATRA data
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    xgb_model = xgb.XGBRegressor(**XGB_PARAMS)
    xgb_model.fit(X, y, verbose=False)

    rf_model = RandomForestRegressor(**RF_PARAMS)
    rf_model.fit(X, y)

    ridge_model = Ridge(alpha=RIDGE_ALPHA)
    ridge_model.fit(X_scaled, y)

    return {
        "xgb": xgb_model,
        "rf": rf_model,
        "ridge": ridge_model,
        "scaler": scaler,
        "loocv_mae_mm": round(mae_mm, 1),
        "loocv_mae_score": round(mae_score, 3),
        "training_steels": len(catra_df),
        "training_steel_names": catra_df["steel_name"].tolist(),
    }


def predict_edge_retention(model, X):
    """Predict CATRA TCC mm, then convert to 1-10 score."""
    xgb_pred = model["xgb"].predict(X)
    rf_pred = model["rf"].predict(X)
    X_scaled = model["scaler"].transform(X)
    ridge_pred = model["ridge"].predict(X_scaled)
    catra_pred = XGB_WEIGHT * xgb_pred + RF_WEIGHT * rf_pred + RIDGE_WEIGHT * ridge_pred
    catra_pred = np.clip(catra_pred, 200, 1200)  # physical bounds
    return catra_pred, catra_to_score(catra_pred)


# ═══════════════════════════════════════════════════════════════════
# TOUGHNESS MODEL (physics-based, calibrated on Charpy data)
# ═══════════════════════════════════════════════════════════════════

def calibrate_toughness_model(df):
    """
    Calibrate toughness model by training Ridge regression on Charpy data.

    Trains a Ridge (alpha=5) on physics-informed features derived from composition.
    Sets global TOUGHNESS_RIDGE and TOUGHNESS_SCALER for use in compute_toughness_score().
    """
    global TOUGHNESS_RIDGE, TOUGHNESS_SCALER

    charpy_df = df[df["charpy_ftlbs"].notna() & (df["charpy_ftlbs"] > 0)].copy()
    print(f"\n  Calibrating toughness model against {len(charpy_df)} steels with Charpy data")

    # Build feature matrix and targets
    X = np.array([get_toughness_physics_features(row) for _, row in charpy_df.iterrows()])
    y = np.array([charpy_to_score(row["charpy_ftlbs"]) for _, row in charpy_df.iterrows()])

    # Train Ridge with moderate regularization (12 samples, 8 features)
    TOUGHNESS_SCALER = StandardScaler()
    X_scaled = TOUGHNESS_SCALER.fit_transform(X)

    TOUGHNESS_RIDGE = Ridge(alpha=5.0)
    TOUGHNESS_RIDGE.fit(X_scaled, y)

    # Evaluate: compute predictions using compute_toughness_score (which now uses the Ridge)
    physics_scores = []
    charpy_scores = []
    for _, row in charpy_df.iterrows():
        physics_scores.append(compute_toughness_score(row))
        charpy_scores.append(charpy_to_score(row["charpy_ftlbs"]))

    physics_arr = np.array(physics_scores)
    charpy_arr = np.array(charpy_scores)

    mae = mean_absolute_error(charpy_arr, physics_arr)
    corr = np.corrcoef(physics_arr, charpy_arr)[0, 1]

    print(f"  Physics vs Charpy correlation: {corr:.3f}")
    print(f"  Physics vs Charpy MAE: {mae:.2f} (on 1-10 scale)")

    # Show per-steel comparison
    print(f"\n  {'Steel':20s} {'Charpy(ft-lb)':>12s} {'Charpy→Score':>12s} {'Physics':>8s} {'Error':>6s}")
    print(f"  {'-'*62}")
    for _, row in charpy_df.iterrows():
        phys = compute_toughness_score(row)
        charpy = charpy_to_score(row["charpy_ftlbs"])
        err = phys - charpy
        print(f"  {row['steel_name']:20s} {row['charpy_ftlbs']:>10.1f} {charpy:>10.1f} {phys:>8.1f} {err:>+6.1f}")

    return {
        "calibration_mae": round(mae, 3),
        "correlation": round(corr, 3),
        "n_steels": len(charpy_df),
        "ridge_coefs": dict(zip(TOUGHNESS_FEATURE_NAMES, TOUGHNESS_RIDGE.coef_.tolist())),
        "ridge_intercept": float(TOUGHNESS_RIDGE.intercept_),
    }


# ═══════════════════════════════════════════════════════════════════
# CORROSION MODEL (pure physics — no training data needed)
# ═══════════════════════════════════════════════════════════════════

def validate_corrosion_model(df):
    """Validate physics-based corrosion against KSN ratings (external reference only).

    KSN ratings are used solely as an independent validation benchmark and are
    NOT redistributed publicly (see the data-use policy / DATA_SOURCES.md). When
    the KSN column is absent — as in the public dataset — validation is skipped
    and the previously reported reference figures are documented instead. The
    corrosion model itself is a deterministic physics calculation and requires
    no training data, so predictions reproduce fully without KSN.
    """
    if "ksn_corrosion_resistance" not in df.columns or df["ksn_corrosion_resistance"].notna().sum() == 0:
        print("\n  KSN validation data not present (kept private) — skipping corrosion validation.")
        print("  Reference (validated privately against 61 KSN ratings): MAE 1.362, r 0.888.")
        return {
            "validation_mae": 1.362,
            "correlation": 0.888,
            "n_steels": 61,
            "note": "Validated privately against 61 KnifeSteelNerds corrosion ratings; "
                    "KSN data is an external validation reference only and is not "
                    "redistributed. Figures shown are from that reference run.",
        }

    ksn_df = df[df["ksn_corrosion_resistance"].notna()].copy()
    print(f"\n  Validating corrosion model against {len(ksn_df)} steels with KSN CR ratings")

    physics_scores = []
    ksn_scores = []
    for _, row in ksn_df.iterrows():
        physics_scores.append(compute_corrosion_score(row))
        ksn_scores.append(row["ksn_corrosion_resistance"])

    physics_arr = np.array(physics_scores)
    ksn_arr = np.array(ksn_scores)

    mae = mean_absolute_error(ksn_arr, physics_arr)
    corr = np.corrcoef(physics_arr, ksn_arr)[0, 1]

    print(f"  Physics vs KSN correlation: {corr:.3f}")
    print(f"  Physics vs KSN MAE: {mae:.2f}")

    # Show worst misses
    errors = np.abs(physics_arr - ksn_arr)
    worst_idx = np.argsort(errors)[-5:]
    print(f"\n  Worst 5 predictions:")
    for idx in worst_idx:
        row = ksn_df.iloc[idx]
        print(f"    {row['steel_name']:20s} Physics={physics_arr[idx]:.1f} KSN={ksn_arr[idx]:.1f} Err={errors[idx]:.1f}")

    return {"validation_mae": round(mae, 3), "correlation": round(corr, 3), "n_steels": len(ksn_df)}


# ═══════════════════════════════════════════════════════════════════
# USE-CASE SCORING
# ═══════════════════════════════════════════════════════════════════

def compute_use_case_scores(toughness, edge_retention, corrosion, ease_of_sharpening):
    """Compute use-case scores from base property scores."""
    properties = {
        "toughness": toughness,
        "edge_retention": edge_retention,
        "corrosion_resistance": corrosion,
        "ease_of_sharpening": ease_of_sharpening,
    }

    scores = {}
    for use_case, weights in USE_CASE_WEIGHTS.items():
        score = sum(weights[prop] * properties[prop] for prop in weights)
        scores[use_case] = round(np.clip(score, 0.5, 10.0), 1)

    return scores


# ═══════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════

def generate_all_predictions(df, er_model):
    """Generate predictions for all steels."""
    X = df[ALL_FEATURES].values
    results = []

    # Edge retention (ML model)
    catra_pred, er_scores = predict_edge_retention(er_model, X)

    for i, (_, row) in enumerate(df.iterrows()):
        steel = row["steel_name"]

        # Toughness (physics)
        toughness = compute_toughness_score(row)

        # Edge retention (ML model trained on CATRA)
        edge_retention = float(er_scores[i])
        predicted_catra_mm = float(catra_pred[i])

        # Corrosion (physics)
        corrosion = compute_corrosion_score(row)

        # Ease of sharpening (physics)
        ease = compute_ease_of_sharpening(row)

        # Use-case scores
        use_cases = compute_use_case_scores(toughness, edge_retention, corrosion, ease)

        results.append({
            "steel_name": steel,
            "toughness": round(toughness, 1),
            "edge_retention": round(edge_retention, 1),
            "corrosion_resistance": round(corrosion, 1),
            "ease_of_sharpening": round(ease, 1),
            "predicted_catra_mm": round(predicted_catra_mm, 0),
            "edc_score": use_cases["edc"],
            "hard_use_score": use_cases["hard_use"],
            "kitchen_score": use_cases["kitchen"],
            "bushcraft_score": use_cases["bushcraft"],
        })

    return pd.DataFrame(results)


def export_model(er_model, toughness_stats, corrosion_stats, predictions_df):
    """Export model weights and predictions."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # Export XGBoost model for edge retention
    xgb_path = MODELS_DIR / "xgb_catra_edge_retention.json"
    er_model["xgb"].save_model(str(xgb_path))

    # Export full model weights
    weights = {
        "version": "2.0.0",
        "methodology": {
            "edge_retention": "XGBoost + RF + Ridge ensemble trained on CATRA TCC mm measurements (objective machine test)",
            "toughness": "Physics-based model (CVF, PM, eutectoid boundary, matrix composition) calibrated against Charpy ft-lbs",
            "corrosion_resistance": "Physics calculation from matrix Cr, PREN, and nitrogen content",
            "ease_of_sharpening": "Physics-based inverse wear resistance (CVF, VC hardness, WC content)",
            "use_case_scores": "Weighted combination of base properties with domain-specific weights",
        },
        "features": ALL_FEATURES,
        "edge_retention_model": {
            "type": "ensemble",
            "training_target": "CATRA TCC mm",
            "training_steels": er_model["training_steels"],
            "loocv_mae_mm": er_model["loocv_mae_mm"],
            "loocv_mae_score": er_model["loocv_mae_score"],
            "weights": {"xgb": XGB_WEIGHT, "rf": RF_WEIGHT, "ridge": RIDGE_WEIGHT},
            "catra_normalization": {"min_mm": CATRA_MIN, "max_mm": CATRA_MAX},
            "ridge": {
                "coefficients": er_model["ridge"].coef_.tolist(),
                "intercept": float(er_model["ridge"].intercept_),
            },
            "scaler": {
                "mean": er_model["scaler"].mean_.tolist(),
                "scale": er_model["scaler"].scale_.tolist(),
            },
        },
        "toughness_model": {
            "type": "physics_formula",
            "calibration": toughness_stats,
            "parameters": {
                "cvf_coefficient": 2.2,
                "pm_bonus_base": 1.2,
                "eutectoid_penalty_factor": 8.0,
                "cr_carbide_penalty_factor": 0.15,
            },
        },
        "corrosion_model": {
            "type": "physics_formula",
            "validation": corrosion_stats,
            "parameters": {
                "stainless_threshold_matrix_cr": 10.5,
                "excellent_threshold_matrix_cr": 18.0,
            },
        },
        "use_case_weights": USE_CASE_WEIGHTS,
        "feature_importance": {},
    }

    # Feature importance from XGBoost
    imp = er_model["xgb"].feature_importances_
    weights["feature_importance"]["edge_retention"] = {
        feat: round(float(val), 4)
        for feat, val in sorted(zip(ALL_FEATURES, imp), key=lambda x: -x[1])
        if val > 0.01
    }

    # Save XGBoost trees
    with open(xgb_path) as f:
        weights["edge_retention_model"]["xgb_trees"] = json.load(f)

    weights_path = MODELS_DIR / "model_weights.json"
    with open(weights_path, "w") as f:
        json.dump(weights, f, indent=2)
    print(f"\n  Exported model weights to {weights_path}")

    # Summary
    summary = {
        "version": "2.0.0",
        "methodology": weights["methodology"],
        "edge_retention_training_steels": er_model["training_steels"],
        "edge_retention_loocv_mae": er_model["loocv_mae_score"],
        "toughness_calibration": toughness_stats,
        "corrosion_validation": corrosion_stats,
        "use_case_weights": USE_CASE_WEIGHTS,
        "feature_importance": weights["feature_importance"],
    }
    summary_path = MODELS_DIR / "model_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Exported model summary to {summary_path}")

    # Predictions CSV
    out_path = PROCESSED_DIR / "all_predictions.csv"
    predictions_df.to_csv(out_path, index=False)
    print(f"  Exported predictions for {len(predictions_df)} steels to {out_path}")


def main():
    print("=" * 70)
    print("STEEL PROPERTY PREDICTOR v2 — MEASUREMENT-BASED TRAINING")
    print("=" * 70)
    print("\nMethodology:")
    print("  Edge Retention: ML model trained on CATRA TCC machine measurements")
    print("  Toughness: Physics formula calibrated on Charpy impact data")
    print("  Corrosion: Physics calculation from matrix Cr / PREN")
    print("  Use Cases: Weighted property combinations (EDC/Hard Use/Kitchen/Bushcraft)")

    # Load data
    df = load_data()

    # ─── Edge Retention (ML on CATRA) ───
    print(f"\n{'='*70}")
    print("EDGE RETENTION MODEL (trained on CATRA TCC measurements)")
    print(f"{'='*70}")
    er_model = train_edge_retention_model(df)

    # ─── Toughness (Physics calibrated on Charpy) ───
    print(f"\n{'='*70}")
    print("TOUGHNESS MODEL (physics, calibrated against Charpy data)")
    print(f"{'='*70}")
    toughness_stats = calibrate_toughness_model(df)

    # ─── Corrosion (Physics, validated against KSN) ───
    print(f"\n{'='*70}")
    print("CORROSION MODEL (physics from matrix Cr / PREN)")
    print(f"{'='*70}")
    corrosion_stats = validate_corrosion_model(df)

    # ─── Generate all predictions ───
    print(f"\n{'='*70}")
    print("GENERATING PREDICTIONS FOR ALL STEELS")
    print(f"{'='*70}")
    predictions_df = generate_all_predictions(df, er_model)

    # ─── Validate against KSN (reference only) ───
    print(f"\n{'='*70}")
    print("VALIDATION vs KSN RATINGS (reference — our model is independent)")
    print(f"{'='*70}")
    has_ksn = "ksn_toughness" in df.columns and df["ksn_toughness"].notna().sum() > 0
    if not has_ksn:
        print("  KSN ratings not present (kept private) — skipping reference comparison.")
    ksn_df = df[df["ksn_toughness"].notna()].copy() if has_ksn else df.iloc[0:0]
    if len(ksn_df) > 0:
        merged = predictions_df.merge(
            df[["steel_name", "ksn_toughness", "ksn_edge_retention", "ksn_corrosion_resistance"]],
            on="steel_name", how="inner"
        )
        merged = merged[merged["ksn_toughness"].notna()]

        for prop, ksn_col in [("toughness", "ksn_toughness"),
                               ("edge_retention", "ksn_edge_retention"),
                               ("corrosion_resistance", "ksn_corrosion_resistance")]:
            valid = merged[merged[ksn_col].notna()]
            if len(valid) > 0:
                mae = mean_absolute_error(valid[ksn_col], valid[prop])
                corr = np.corrcoef(valid[prop], valid[ksn_col])[0, 1]
                print(f"  {prop:25s} vs KSN: MAE={mae:.2f}, r={corr:.3f} (n={len(valid)})")

    # ─── Show popular steels ───
    print(f"\n{'='*70}")
    print("POPULAR STEELS — PREDICTION SUMMARY")
    print(f"{'='*70}")
    popular = ["CPM S30V", "CPM S35VN", "M390", "CPM MagnaCut", "1095", "D2",
               "VG-10", "14C28N", "CPM 3V", "ZDP-189", "CPM S90V", "AUS-8",
               "Elmax", "Maxamet", "154CM", "440C"]
    pop_df = predictions_df[predictions_df["steel_name"].isin(popular)]
    if len(pop_df) > 0:
        print(f"\n  {'Steel':20s} {'Tough':>5s} {'ER':>5s} {'Corr':>5s} {'Shrp':>5s} | {'EDC':>4s} {'Hard':>5s} {'Kit':>4s} {'Bush':>5s}")
        print(f"  {'-'*75}")
        for _, row in pop_df.sort_values("edc_score", ascending=False).iterrows():
            print(f"  {row['steel_name']:20s} {row['toughness']:5.1f} {row['edge_retention']:5.1f} "
                  f"{row['corrosion_resistance']:5.1f} {row['ease_of_sharpening']:5.1f} | "
                  f"{row['edc_score']:4.1f} {row['hard_use_score']:5.1f} {row['kitchen_score']:4.1f} {row['bushcraft_score']:5.1f}")

    # ─── Export ───
    print(f"\n{'='*70}")
    print("EXPORTING MODEL")
    print(f"{'='*70}")
    export_model(er_model, toughness_stats, corrosion_stats, predictions_df)

    # ─── Final summary ───
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Edge retention: {er_model['training_steels']} steels, LOOCV MAE={er_model['loocv_mae_score']:.3f}")
    print(f"  Toughness: physics model, calibration r={toughness_stats['correlation']:.3f}")
    print(f"  Corrosion: physics model, validation r={corrosion_stats['correlation']:.3f}")
    print(f"  Total steels predicted: {len(predictions_df)}")
    print(f"  Use-case scores: EDC, Hard Use, Kitchen, Bushcraft")
    print(f"\n  Model v2 complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
