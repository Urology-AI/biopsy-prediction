#!/usr/bin/env python3
"""
Refit ePSA Part 2 model (Cancer risk: csPCa GG>=2 or GG>=3).

Label:
  ClinicallySignificant = 1 if Grade Group >= 2 else 0   (default)
  Use --outcome gg3plus to target GG>=3 (high-grade only)
  Parsed from 'Final Path' (supports "GG2", "Grade Group 2", "Gleason 3+4", etc.)

Predictors (default, no MRI):
  logPSA
With --include_mri:
  logPSA + PIRADS dummies: pirads_3, pirads_4, pirads_5 (ref: <=2 / missing)
With --include_demographics (adds to either):
  age bins + raceBlack + fhBinary + BMI bins

Outputs:
  - pooled out-of-fold AUC + Brier score
  - threshold table
  - deploy intercept + weights for calculatorConfig.js (base and mri models)
  - sanity check warnings for counterintuitive coefficient directions
"""

from __future__ import annotations
import argparse
import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.metrics import roc_auc_score, brier_score_loss


BLACK_VALUES = {
    "black", "black or african american", "african american", "black/aa", "black/african american"
}

def normalize_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip().lower()

def safe_log_psa(psa: float) -> float:
    return float(np.log(max(psa, 0.1)))

def parse_grade_group(final_path: str) -> Optional[int]:
    """
    Attempt to parse Grade Group from a free-text pathology string.
    Handles common patterns:
      - "GG1", "GG 2", "Grade Group 3"
      - "Gleason 3+4" => GG2
      - "Gleason 4+3" => GG3
      - "Gleason 4+4" => GG4
      - "Gleason 4+5/5+4/5+5" => GG5
      - "benign", "negative", "no cancer" => GG0 (no cancer)
    Returns int 0..5 or None if cannot parse.
    """
    s = normalize_str(final_path)
    if not s:
        return None

    # Explicit benign / negative
    if any(k in s for k in ["benign", "negative", "no cancer", "no malignancy", "nml", "normal"]):
        return 0

    # Direct "grade group"
    m = re.search(r"(grade\s*group|gg)\s*[:\-]?\s*(\d)", s)
    if m:
        gg = int(m.group(2))
        if 0 <= gg <= 5:
            return gg

    # Gleason patterns like 3+4, 4+3, etc.
    m = re.search(r"gleason\s*(score)?\s*[:\-]?\s*(\d)\s*\+\s*(\d)", s)
    if m:
        a = int(m.group(2))
        b = int(m.group(3))
        if (a, b) == (3, 3):
            return 1
        if (a, b) == (3, 4):
            return 2
        if (a, b) == (4, 3):
            return 3
        if (a, b) == (4, 4):
            return 4
        if a == 5 or b == 5:
            return 5

    return None

@dataclass
class Cols:
    psa: str = "PSA"
    pirads: str = "PIRADS"
    final_path: str = "Final Path"
    clinically_significant: str = "ClinicallySignificant"  # pre-labeled column; used if present
    knowledge_psa: str = "Knowledge of PSA level"
    knowledge_pirads: str = "Knowledge of PIRADS Score"
    # Optional demographics
    age_group: str = "Age Group"
    race: str = "Race.1"          # dataset uses Race.1 for the coded race field
    bmi: str = "BMI"
    family_history: str = "FH of prostate"

def age_group_midpoint(age_group: str) -> Optional[float]:
    s = normalize_str(age_group)
    if not s:
        return None
    m = re.match(r"^(\d{2,3})\+$", s)
    if m:
        base = float(m.group(1))
        return base + 5.0
    m = re.match(r"^(\d{2,3})\s*-\s*(\d{2,3})$", s)
    if m:
        a = float(m.group(1)); b = float(m.group(2))
        return (a + b) / 2.0
    try:
        return float(s)
    except Exception:
        return None

def recode_family_history_to_binary(x) -> int:
    s = normalize_str(x)
    if not s:
        return 0
    if s in ("yes", "y", "true", "1"):
        return 1
    if s in ("no", "n", "false", "0"):
        return 0
    try:
        v = float(s)
        return 1 if v > 0 else 0
    except Exception:
        pass
    return 1

AGE_BINS = [(40, 49, "40-49"), (50, 59, "50-59"), (60, 69, "60-69"), (70, 200, "70+")]
BMI_BINS = [(0, 24.999, "<25"), (25, 29.999, "25-29.9"), (30, 200, ">=30")]

def pick_bin_label(x: float, bins: List[Tuple[float, float, str]], default: str) -> str:
    if x is None or not np.isfinite(x):
        return default
    for lo, hi, label in bins:
        if x >= lo and x <= hi:
            return label
    return default


# -------------------------
# Sanity checks
# -------------------------

# Expected positive direction for csPCa outcome.
EXPECTED_POSITIVE_PART2 = {
    "logPSA",
    "pirads_4", "pirads_5",   # higher PIRADS = more likely cancer
    "age_60_69", "age_70_plus",
    "raceBlack",
    "fhBinary",
    "bmi_ge_30",
}

# Monotonicity within PIRADS dummies (relative to ref ≤2):
# pirads_3 can go either way clinically (equivocal), so not checked.
# pirads_4 should be < pirads_5.
MONOTONICITY_PART2 = [
    ("pirads_4", "pirads_5"),
    ("age_50_59", "age_60_69", "age_70_plus"),
]

def run_sanity_checks_part2(weights: Dict[str, float]) -> List[str]:
    issues = []
    for vid, w in weights.items():
        if vid in EXPECTED_POSITIVE_PART2 and w < 0:
            issues.append(
                f"  ⚠  {vid}: expected POSITIVE coefficient but got {w:.4f}."
            )
    for group in MONOTONICITY_PART2:
        present = [v for v in group if v in weights]
        if len(present) < 2:
            continue
        vals = [weights[v] for v in present]
        for i in range(len(vals) - 1):
            if vals[i] > vals[i + 1]:
                issues.append(
                    f"  ⚠  Monotonicity violated: {present[i]} ({vals[i]:.4f}) > "
                    f"{present[i+1]} ({vals[i+1]:.4f})."
                )
    return issues


# -------------------------
# Feature builder
# -------------------------

def build_features(
    df: pd.DataFrame,
    cols: Cols,
    include_mri: bool,
    include_demographics: bool,
    outcome_gg_threshold: int,
) -> Tuple[pd.DataFrame, pd.Series]:
    psa = pd.to_numeric(df[cols.psa], errors="coerce")

    # Use pre-labeled ClinicallySignificant column if present, else parse Final Path
    if cols.clinically_significant in df.columns:
        raw_cs = df[cols.clinically_significant]
        # Support numeric (0/1), boolean, or string (Yes/No)
        def parse_cs(v):
            s = normalize_str(v)
            if s in ("1", "yes", "y", "true"):
                return 1
            if s in ("0", "no", "n", "false"):
                return 0
            try:
                return int(float(s))
            except Exception:
                return None
        y_raw = raw_cs.apply(parse_cs)
        y = pd.to_numeric(y_raw, errors="coerce")
        outcome_valid = y.notna()
    else:
        gg = df[cols.final_path].apply(parse_grade_group)
        gg = pd.to_numeric(gg, errors="coerce")
        y = (gg >= outcome_gg_threshold).astype(float)
        y[gg.isna()] = np.nan
        outcome_valid = gg.notna()

    # Filter: only rows where patient knew their PSA
    if cols.knowledge_psa in df.columns:
        knows_psa = df[cols.knowledge_psa].apply(normalize_str).isin(["yes", "y", "1", "true"])
    else:
        knows_psa = pd.Series(True, index=df.index)

    X = pd.DataFrame(index=df.index)
    X["logPSA"] = psa.apply(lambda v: safe_log_psa(v) if np.isfinite(v) else np.nan)

    mask = outcome_valid & psa.notna() & knows_psa

    if include_mri:
        pirads = pd.to_numeric(df[cols.pirads], errors="coerce")
        X["pirads_3"] = (pirads == 3).astype(int)
        X["pirads_4"] = (pirads == 4).astype(int)
        X["pirads_5"] = (pirads == 5).astype(int)
        # For MRI model, also filter to rows where patient knew their PIRADS
        if cols.knowledge_pirads in df.columns:
            knows_pirads = df[cols.knowledge_pirads].apply(normalize_str).isin(["yes", "y", "1", "true"])
        else:
            knows_pirads = pd.Series(True, index=df.index)
        mask = mask & pirads.notna() & knows_pirads

    if include_demographics:
        age_mid = pd.to_numeric(df[cols.age_group].apply(age_group_midpoint), errors="coerce")
        age_bin = age_mid.apply(lambda v: pick_bin_label(v, AGE_BINS, "40-49"))
        X["age_50_59"] = (age_bin == "50-59").astype(int)
        X["age_60_69"] = (age_bin == "60-69").astype(int)
        X["age_70_plus"] = (age_bin == "70+").astype(int)

        bmi = pd.to_numeric(df[cols.bmi], errors="coerce")
        bmi_bin = bmi.apply(lambda v: pick_bin_label(v, BMI_BINS, "<25"))
        X["bmi_25_29_9"] = (bmi_bin == "25-29.9").astype(int)
        X["bmi_ge_30"] = (bmi_bin == ">=30").astype(int)

        race_norm = df[cols.race].apply(normalize_str)
        X["raceBlack"] = race_norm.isin(BLACK_VALUES).astype(int)
        X["fhBinary"] = df[cols.family_history].apply(recode_family_history_to_binary).astype(int)

    X = X.loc[mask].copy()
    y = y.loc[mask].copy().astype(int)
    return X, y


# -------------------------
# Threshold table
# -------------------------

def threshold_table(y_true: np.ndarray, prob: np.ndarray) -> List[Dict]:
    rows = []
    for t in np.arange(0.05, 0.96, 0.05):
        y_hat = (prob >= t).astype(int)
        tp = np.sum((y_true == 1) & (y_hat == 1))
        fn = np.sum((y_true == 1) & (y_hat == 0))
        tn = np.sum((y_true == 0) & (y_hat == 0))
        fp = np.sum((y_true == 0) & (y_hat == 1))
        sens = tp / (tp + fn) if (tp + fn) else 0.0
        spec = tn / (tn + fp) if (tn + fp) else 0.0
        ppv  = tp / (tp + fp) if (tp + fp) else 0.0
        npv  = tn / (tn + fn) if (tn + fn) else 0.0
        rows.append({
            "threshold": round(float(t), 2),
            "sensitivity": round(sens, 3),
            "specificity": round(spec, 3),
            "ppv": round(ppv, 3),
            "npv": round(npv, 3),
        })
    return rows


# -------------------------
# Single model fit + output
# -------------------------

def fit_and_report(
    X: pd.DataFrame,
    y: pd.Series,
    label: str,
    args,
    outcome_label: str,
) -> Dict:
    rskf = RepeatedStratifiedKFold(n_splits=args.splits, n_repeats=args.repeats, random_state=42)
    oof_prob = np.zeros(len(y), dtype=float)

    for train_idx, test_idx in rskf.split(X, y):
        m = LogisticRegression(penalty="l2", C=args.C, solver="liblinear", max_iter=5000)
        m.fit(X.iloc[train_idx], y.iloc[train_idx])
        oof_prob[test_idx] = m.predict_proba(X.iloc[test_idx])[:, 1]

    auc = roc_auc_score(y, oof_prob)
    brier = brier_score_loss(y, oof_prob)

    # Deploy fit on full data
    model = LogisticRegression(penalty="l2", C=args.C, solver="liblinear", max_iter=5000)
    model.fit(X, y)

    intercept = float(model.intercept_[0])
    weights = {fn: float(w) for fn, w in zip(X.columns, model.coef_[0])}

    ordered = list(X.columns)
    variables = [
        {
            "id": vid,
            "name": vid,
            "weight": weights[vid],
            "type": "continuous" if vid == "logPSA" else "binary"
        }
        for vid in ordered
    ]

    # Sanity checks
    issues = run_sanity_checks_part2(weights)

    result = {
        "model": label,
        "outcome": outcome_label,
        "n_used": int(len(y)),
        "prevalence": float(y.mean()),
        "auc_oof": float(auc),
        "brier_oof": float(brier),
        "sanity_issues": issues,
        "deploy": {
            "intercept": intercept,
            "variables": variables,
            "encodings": {"psaTransform": "log", "piradsMode": "dummies" if "pirads_3" in weights else "none"}
        }
    }
    return result, weights, intercept, variables, issues


def print_config_block(label: str, intercept: float, variables: List[Dict], issues: List[str]):
    print(f"\n----- {label}: paste into calculatorConfig.js -----")
    if issues:
        print("  !!! Sanity check warnings above — review before deploying !!!")
    print(f"intercept: {intercept:.6f},")
    print("encodings: { psaTransform: 'log', piradsMode: 'dummies' },") if any(v["id"].startswith("pirads") for v in variables) else print("encodings: { psaTransform: 'log', piradsMode: 'none' },")
    print("variables: [")
    for v in variables:
        print(f"  {{ id: '{v['id']}', name: '{v['id']}', weight: {v['weight']:.6f}, type: '{v['type']}' }},")
    print("],")


# -------------------------
# Main
# -------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--repeats", type=int, default=100)
    ap.add_argument("--splits", type=int, default=5)
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument(
        "--outcome", choices=["gg2plus", "gg3plus"], default="gg2plus",
        help="gg2plus = GG>=2 (any csPCa); gg3plus = GG>=3 (high-grade only)"
    )
    ap.add_argument(
        "--include_mri", action="store_true",
        help="Fit MRI model (logPSA + PIRADS dummies). Requires PIRADS column."
    )
    ap.add_argument(
        "--include_demographics", action="store_true",
        help="Add age bins, race, FH, BMI to both base and MRI models."
    )
    ap.add_argument(
        "--fit_both", action="store_true",
        help="Fit both base (no MRI) and MRI models in one run. Overrides --include_mri."
    )
    args = ap.parse_args()

    if args.xlsx.lower().endswith(".csv"):
        df = pd.read_csv(args.xlsx)
    else:
        df = pd.read_excel(args.xlsx, sheet_name=args.sheet)
        if isinstance(df, dict):
            sheet_name = next(iter(df))
            df = df[sheet_name]
    df.columns = df.columns.str.strip()

    cols = Cols()
    outcome_gg_threshold = 3 if args.outcome == "gg3plus" else 2
    outcome_label = f"GG>={outcome_gg_threshold}"

    # Validate required columns — ClinicallySignificant takes priority over Final Path
    if cols.clinically_significant in df.columns:
        print(f"\nOutcome source: '{cols.clinically_significant}' column (pre-labeled)")
    elif cols.final_path in df.columns:
        print(f"\nOutcome source: '{cols.final_path}' column (parsed, GG>={outcome_gg_threshold})")
    else:
        raise ValueError(
            f"Neither '{cols.clinically_significant}' nor '{cols.final_path}' found. "
            f"Available: {list(df.columns)}"
        )
    if (args.include_mri or args.fit_both) and cols.pirads not in df.columns:
        raise ValueError(f"PIRADS column '{cols.pirads}' not found. Available: {list(df.columns)}")

    # Print outcome distribution
    # Uses the same int(float(s)) parsing as build_features to handle float-stored values
    # (e.g. 1.0/0.0). Prior isin(["1","0"]) string match silently showed 0/0/N (false alarm).
    if cols.clinically_significant in df.columns:
        def _count_cs(v):
            s = normalize_str(v)
            if s in ("1", "yes", "y", "true"): return 1
            if s in ("0", "no", "n", "false"): return 0
            try:
                iv = int(float(s))
                return iv if iv in (0, 1) else None
            except Exception:
                return None
        cs_parsed = df[cols.clinically_significant].apply(_count_cs)
        n_pos = (cs_parsed == 1).sum()
        n_neg = (cs_parsed == 0).sum()
        print(f"  ClinicallySignificant=1: n={n_pos}")
        print(f"  ClinicallySignificant=0: n={n_neg}")
        print(f"  Missing / unparseable:   n={len(df) - n_pos - n_neg}")
    else:
        gg_parsed = df[cols.final_path].apply(parse_grade_group)
        print(f"Grade Group distribution in dataset:")
        for gg_val in sorted(gg_parsed.dropna().unique()):
            n = (gg_parsed == gg_val).sum()
            label = f"GG{int(gg_val)}" if gg_val > 0 else "Benign/GG0"
            print(f"  {label}: n={n}")
        print(f"  Unparseable / missing: n={gg_parsed.isna().sum()}")

    # Print knowledge filter counts
    if cols.knowledge_psa in df.columns:
        n_knows_psa = df[cols.knowledge_psa].apply(normalize_str).isin(["yes", "y", "1", "true"]).sum()
        print(f"\nKnows PSA: {n_knows_psa} / {len(df)} rows — base model will use these")
    if cols.knowledge_pirads in df.columns:
        n_knows_pirads = df[cols.knowledge_pirads].apply(normalize_str).isin(["yes", "y", "1", "true"]).sum()
        print(f"Knows PIRADS: {n_knows_pirads} / {len(df)} rows — MRI model will use these")

    results = []

    # Base model (no MRI)
    if not args.include_mri or args.fit_both:
        X_base, y_base = build_features(
            df, cols,
            include_mri=False,
            include_demographics=args.include_demographics,
            outcome_gg_threshold=outcome_gg_threshold,
        )
        print(f"\nBase model: {len(y_base)} rows, {y_base.sum()} {outcome_label} ({y_base.mean()*100:.1f}%)")
        res, w, intercept, variables, issues = fit_and_report(X_base, y_base, "base", args, outcome_label)
        results.append(res)
        if issues:
            print(f"\n===== BASE MODEL SANITY WARNINGS =====")
            for msg in issues:
                print(msg)
        else:
            print("✓ Base model sanity checks passed.")
        print_config_block("BASE model (no MRI)", intercept, variables, issues)

    # MRI model
    if args.include_mri or args.fit_both:
        X_mri, y_mri = build_features(
            df, cols,
            include_mri=True,
            include_demographics=args.include_demographics,
            outcome_gg_threshold=outcome_gg_threshold,
        )
        print(f"\nMRI model: {len(y_mri)} rows, {y_mri.sum()} {outcome_label} ({y_mri.mean()*100:.1f}%)")
        res_mri, w_mri, intercept_mri, variables_mri, issues_mri = fit_and_report(
            X_mri, y_mri, "mri", args, outcome_label
        )
        results.append(res_mri)
        if issues_mri:
            print(f"\n===== MRI MODEL SANITY WARNINGS =====")
            for msg in issues_mri:
                print(msg)
        else:
            print("✓ MRI model sanity checks passed.")
        print_config_block("MRI model (logPSA + PIRADS)", intercept_mri, variables_mri, issues_mri)

        # Threshold table for MRI model (most clinically relevant)
        X_mri_arr, y_mri_arr = X_mri.to_numpy(), y_mri.to_numpy()
        rskf = RepeatedStratifiedKFold(n_splits=args.splits, n_repeats=args.repeats, random_state=42)
        oof = np.zeros(len(y_mri_arr))
        for tr, te in rskf.split(X_mri_arr, y_mri_arr):
            m = LogisticRegression(penalty="l2", C=args.C, solver="liblinear", max_iter=5000)
            m.fit(X_mri_arr[tr], y_mri_arr[tr])
            oof[te] = m.predict_proba(X_mri_arr[te])[:, 1]
        tbl = threshold_table(y_mri_arr, oof)
        print("\n----- MRI Model threshold table (OOF) -----")
        print(f"{'Threshold':>10}  {'Sens':>6}  {'Spec':>6}  {'PPV':>6}  {'NPV':>6}")
        for row in tbl:
            print(f"  {row['threshold']:>8.2f}  {row['sensitivity']:>6.3f}  {row['specificity']:>6.3f}  {row['ppv']:>6.3f}  {row['npv']:>6.3f}")

    print("\n===== PART 2 FULL RESULTS =====")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
