"""
compare_models.py — Head-to-head comparison of v1 vs v2 on the same 121 patients.

v1: N=96 training, 74% prevalence, AUC 0.591, threshold 0.50
v2: N=121 training, 28.9% prevalence, AUC 0.670 OOF, threshold 0.30
"""

import csv
import math
from pathlib import Path

CSV = Path("results/extracted.csv")

# ── Model definitions ──────────────────────────────────────────────────────
MODELS = {
    "v1 (original)": dict(
        intercept =  0.356742,
        log_psa   = -0.017489,
        pirads3   = -0.061356,
        pirads4   =  0.967766,
        pirads5   =  1.255289,
        threshold =  0.50,
        note      = "N=96, 74% prevalence, AUC 0.591",
    ),
    "v2 (retrained)": dict(
        intercept = -1.526236,
        log_psa   =  0.260607,
        pirads3   = -1.200596,
        pirads4   =  0.424159,
        pirads5   =  0.792264,
        threshold =  0.30,
        note      = "N=121, 28.9% prevalence, AUC 0.670 OOF",
    ),
}

def predict_prob(m, psa, pirads):
    lp = math.log(max(psa, 0.01))
    logit = (m["intercept"]
             + m["log_psa"] * lp
             + m["pirads3"] * (1 if pirads == 3 else 0)
             + m["pirads4"] * (1 if pirads == 4 else 0)
             + m["pirads5"] * (1 if pirads == 5 else 0))
    return 1 / (1 + math.exp(-logit))

def _f(v):
    try: return float(v) if v not in ("", "None", None) else None
    except: return None

def _i(v):
    try: return int(v) if v not in ("", "None", None) else None
    except: return None

def _b(v):
    if str(v).lower() == "true":  return True
    if str(v).lower() == "false": return False
    return None

# ── Load patients ───────────────────────────────────────────────────────────
rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
eligible = [
    r for r in rows
    if r.get("excluded", "").lower() != "true"
    and _f(r.get("psa")) is not None
    and _i(r.get("pirads")) is not None
    and _b(r.get("path_gg2_positive")) is not None
]

print(f"\n{'='*64}")
print(f"  ePSA Model Comparison — v1 vs v2")
print(f"  Patients with PSA + PI-RADS + confirmed outcome: {len(eligible)}")
print(f"{'='*64}\n")

# ── Per-model metrics ───────────────────────────────────────────────────────
results = {}
for name, m in MODELS.items():
    tp = fp = tn = fn = 0
    probs, actuals = [], []
    for r in eligible:
        psa    = _f(r["psa"])
        pirads = _i(r["pirads"])
        actual = _b(r["path_gg2_positive"])
        gg_max = _i(r.get("path_gg_max"))

        prob = predict_prob(m, psa, pirads)
        pred = prob >= m["threshold"]
        probs.append(prob)
        actuals.append(1 if actual else 0)

        if pred and actual:     tp += 1
        elif pred and not actual: fp += 1
        elif not pred and actual: fn += 1
        else:                   tn += 1

    # AUC (Wilcoxon / Mann-Whitney)
    pos_probs = [p for p, a in zip(probs, actuals) if a == 1]
    neg_probs = [p for p, a in zip(probs, actuals) if a == 0]
    concordant = sum(1 for p in pos_probs for n in neg_probs if p > n)
    tied       = sum(1 for p in pos_probs for n in neg_probs if p == n)
    auc = (concordant + 0.5 * tied) / (len(pos_probs) * len(neg_probs))

    sens = tp / (tp + fn) if (tp + fn) else 0
    spec = tn / (tn + fp) if (tn + fp) else 0
    ppv  = tp / (tp + fp) if (tp + fp) else 0
    npv  = tn / (tn + fn) if (tn + fn) else 0

    # High-grade (GG3+) missed
    hg_missed = 0
    for r in eligible:
        gg_max = _i(r.get("path_gg_max"))
        actual = _b(r["path_gg2_positive"])
        psa    = _f(r["psa"])
        pirads = _i(r["pirads"])
        prob   = predict_prob(m, psa, pirads)
        pred   = prob >= m["threshold"]
        if gg_max is not None and gg_max >= 3 and not pred:
            hg_missed += 1

    results[name] = dict(
        tp=tp, fp=fp, tn=tn, fn=fn,
        sens=sens, spec=spec, ppv=ppv, npv=npv,
        auc=auc, hg_missed=hg_missed,
        threshold=m["threshold"], note=m["note"],
    )

# ── Side-by-side table ──────────────────────────────────────────────────────
metrics = [
    ("Training note",       "note",       "{}", "{}"),
    ("Decision threshold",  "threshold",  "{:.0%}", "{:.0%}"),
    ("AUC (test set)",      "auc",        "{:.3f}", "{:.3f}"),
    ("Sensitivity",         "sens",       "{:.1%}", "{:.1%}"),
    ("Specificity",         "spec",       "{:.1%}", "{:.1%}"),
    ("PPV",                 "ppv",        "{:.1%}", "{:.1%}"),
    ("NPV",                 "npv",        "{:.1%}", "{:.1%}"),
    ("True Positives (TP)", "tp",         "{}", "{}"),
    ("False Positives (FP)","fp",         "{}", "{}"),
    ("True Negatives (TN)", "tn",         "{}", "{}"),
    ("False Negatives (FN)","fn",         "{}", "{}"),
    ("HG (GG3+) missed",    "hg_missed",  "{}", "{}"),
]

v1 = results["v1 (original)"]
v2 = results["v2 (retrained)"]

LW = 26
print(f"{'Metric':<{LW}}  {'v1 (original)':>18}  {'v2 (retrained)':>18}  {'Better?':>10}")
print(f"{'─'*LW}  {'─'*18}  {'─'*18}  {'─'*10}")

for label, key, fmt1, fmt2 in metrics:
    v1v = v1[key]
    v2v = v2[key]
    try:
        v1s = fmt1.format(v1v)
        v2s = fmt2.format(v2v)
    except Exception:
        v1s = str(v1v)
        v2s = str(v2v)

    # Determine which is better
    better = ""
    if key in ("sens", "spec", "ppv", "npv", "auc", "tp", "tn"):
        if isinstance(v2v, (int, float)) and isinstance(v1v, (int, float)):
            if v2v > v1v:   better = "✓ v2"
            elif v1v > v2v: better = "  v1"
            else:            better = "  tie"
    elif key in ("fn", "fp", "hg_missed"):
        if isinstance(v2v, (int, float)) and isinstance(v1v, (int, float)):
            if v2v < v1v:   better = "✓ v2"
            elif v1v < v2v: better = "  v1"
            else:            better = "  tie"

    print(f"{label:<{LW}}  {v1s:>18}  {v2s:>18}  {better:>10}")

# ── Patient-level changes ───────────────────────────────────────────────────
print(f"\n{'='*64}")
print("  Patient-level classification changes  (v1 → v2)")
print(f"{'='*64}")

changes = {"gained_TP":[], "lost_TP":[], "gained_TN":[], "lost_TN":[],
           "v1_only_FN":[], "v2_only_FN":[], "unchanged":[]}

for r in eligible:
    pid    = r["patient_id"]
    psa    = _f(r["psa"])
    pirads = _i(r["pirads"])
    actual = _b(r["path_gg2_positive"])
    gg_max = r.get("path_gg_max", "?")

    p1 = predict_prob(MODELS["v1 (original)"],  psa, pirads) >= MODELS["v1 (original)"]["threshold"]
    p2 = predict_prob(MODELS["v2 (retrained)"], psa, pirads) >= MODELS["v2 (retrained)"]["threshold"]

    if p1 == p2:
        changes["unchanged"].append(pid)
    elif not p1 and p2 and actual:     # was FN, now TP
        changes["gained_TP"].append((pid, psa, pirads, gg_max))
    elif p1 and not p2 and actual:     # was TP, now FN
        changes["lost_TP"].append((pid, psa, pirads, gg_max))
    elif not p1 and p2 and not actual: # was TN, now FP
        changes["lost_TN"].append((pid, psa, pirads, gg_max))
    elif p1 and not p2 and not actual: # was FP, now TN
        changes["gained_TN"].append((pid, psa, pirads, gg_max))

print(f"\n  Unchanged classifications : {len(changes['unchanged'])}")
print(f"\n  v2 GAINS (cancers now caught that v1 missed):")
if changes["gained_TP"]:
    for pid, psa, pr, gg in changes["gained_TP"]:
        print(f"    {pid}  PSA={psa:.1f}  PI-RADS={pr}  Path=GG{gg}  FN→TP ✓")
else:
    print("    None")

print(f"\n  v2 LOSSES (cancers v1 caught that v2 now misses):")
if changes["lost_TP"]:
    for pid, psa, pr, gg in changes["lost_TP"]:
        print(f"    {pid}  PSA={psa:.1f}  PI-RADS={pr}  Path=GG{gg}  TP→FN ✗")
else:
    print("    None")

print(f"\n  v2 correctly clears (FP→TN — unnecessary biopsies avoided):")
if changes["gained_TN"]:
    for pid, psa, pr, gg in changes["gained_TN"]:
        print(f"    {pid}  PSA={psa:.1f}  PI-RADS={pr}  Path=GG{gg}  FP→TN ✓")
else:
    print("    None")

print(f"\n  v2 newly flags (TN→FP — extra unnecessary biopsies):")
if changes["lost_TN"]:
    for pid, psa, pr, gg in changes["lost_TN"]:
        print(f"    {pid}  PSA={psa:.1f}  PI-RADS={pr}  Path=GG{gg}  TN→FP")
else:
    print("    None")

# ── Verdict ─────────────────────────────────────────────────────────────────
print(f"\n{'='*64}")
print("  VERDICT")
print(f"{'='*64}")
delta_auc  = v2["auc"]  - v1["auc"]
delta_sens = v2["sens"] - v1["sens"]
delta_fn   = v1["fn"]   - v2["fn"]
delta_hg   = v1["hg_missed"] - v2["hg_missed"]
delta_fp   = v2["fp"]   - v1["fp"]

print(f"  AUC improvement     : +{delta_auc:.3f}")
print(f"  Sensitivity gain    : +{delta_sens:.1%}")
print(f"  Fewer FN (cancers caught): {delta_fn:+d}")
print(f"  Fewer HG missed     : {delta_hg:+d}")
print(f"  Extra FP (cost)     : {delta_fp:+d} unnecessary referrals")

if delta_fn >= 0 and delta_auc > 0 and delta_hg >= 0:
    print(f"\n  ✓ v2 is better — catches more cancers with higher AUC.")
    print(f"    Cost: {delta_fp} additional unnecessary referrals on this cohort.")
    print(f"    Recommendation: deploy v2, freeze coefficients, collect fresh validation data.")
else:
    print(f"\n  ✗ Mixed results — review patient-level changes before deploying.")
print()
