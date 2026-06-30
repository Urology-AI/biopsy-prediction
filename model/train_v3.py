"""
train_v3.py — Retrain ePSA Model v3 adding PSAD as a continuous predictor.

Predictors: logPSA + PSAD + PI-RADS dummies (ref: PI-RADS 1-2)
Data: extracted.csv — patients with PSA + PI-RADS + PSAD + confirmed outcome
"""

import csv, math
import numpy as np
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.metrics import roc_auc_score

CSV = Path("results/extracted.csv")

def _f(v):
    try: return float(v) if v not in ("","None",None) else None
    except: return None
def _i(v):
    try: return int(v) if v not in ("","None",None) else None
    except: return None
def _b(v):
    if str(v).lower() == "true":  return 1
    if str(v).lower() == "false": return 0
    return None

# ── Load ────────────────────────────────────────────────────────────────────
rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
eligible = [
    r for r in rows
    if r.get("excluded","").lower() != "true"
    and _f(r.get("psa"))    is not None
    and _i(r.get("pirads")) is not None
    and _f(r.get("psad"))   is not None
    and _b(r.get("path_gg2_positive")) is not None
]

print(f"\n{'='*60}")
print(f"  ePSA v3 — logPSA + PSAD + PI-RADS dummies")
print(f"  N={len(eligible)} patients with PSA + PSAD + PI-RADS + outcome")
pos = sum(1 for r in eligible if _b(r["path_gg2_positive"])==1)
print(f"  GG≥2 positive: {pos}/{len(eligible)} ({100*pos/len(eligible):.1f}%)")
print(f"{'='*60}\n")

# ── Features ────────────────────────────────────────────────────────────────
X, y = [], []
for r in eligible:
    psa    = _f(r["psa"])
    psad   = _f(r["psad"])
    pirads = _i(r["pirads"])
    outcome= _b(r["path_gg2_positive"])
    X.append([
        math.log(max(psa, 0.01)),  # logPSA
        psad,                       # PSAD (continuous)
        1 if pirads == 3 else 0,   # pirads_3
        1 if pirads == 4 else 0,   # pirads_4
        1 if pirads == 5 else 0,   # pirads_5
    ])
    y.append(outcome)

X = np.array(X, dtype=float)
y = np.array(y, dtype=int)
feat_names = ["logPSA", "PSAD", "pirads_3", "pirads_4", "pirads_5"]

# ── Cross-validated AUC ─────────────────────────────────────────────────────
rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=100, random_state=42)
oof  = np.zeros(len(y))
for tr, te in rskf.split(X, y):
    m = LogisticRegression(penalty="l2", C=1.0, solver="liblinear", max_iter=5000)
    m.fit(X[tr], y[tr])
    oof[te] = m.predict_proba(X[te])[:, 1]

auc_oof = roc_auc_score(y, oof)
print(f"  OOF AUC (5-fold × 100 repeats): {auc_oof:.4f}")

# ── Full-data fit (deploy weights) ──────────────────────────────────────────
model = LogisticRegression(penalty="l2", C=1.0, solver="liblinear", max_iter=5000)
model.fit(X, y)
intercept = float(model.intercept_[0])
weights   = {fn: float(w) for fn, w in zip(feat_names, model.coef_[0])}

print(f"\n  Coefficients:")
print(f"    intercept : {intercept:.6f}")
for fn, w in weights.items():
    direction = "✓" if w > 0 and fn != "pirads_3" else ("?" if fn == "pirads_3" else "✗")
    print(f"    {fn:<12}: {w:+.6f}  {direction}")

# ── Threshold table ─────────────────────────────────────────────────────────
print(f"\n  OOF Threshold table:")
print(f"  {'Threshold':>10}  {'Sens':>7}  {'Spec':>7}  {'PPV':>7}  {'NPV':>7}  {'FN':>4}  {'HG miss':>8}")
for t in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    pred = (oof >= t).astype(int)
    tp = np.sum((y==1)&(pred==1)); fn = np.sum((y==1)&(pred==0))
    tn = np.sum((y==0)&(pred==0)); fp = np.sum((y==0)&(pred==1))
    sens = tp/(tp+fn) if (tp+fn) else 0
    spec = tn/(tn+fp) if (tn+fp) else 0
    ppv  = tp/(tp+fp) if (tp+fp) else 0
    npv  = tn/(tn+fn) if (tn+fn) else 0
    print(f"  {t:>10.2f}  {sens:>7.1%}  {spec:>7.1%}  {ppv:>7.1%}  {npv:>7.1%}  {int(fn):>4}  {'—':>8}")

# ── Head-to-head: v1 vs v2 vs v3 on same patients ───────────────────────────
print(f"\n{'='*60}")
print(f"  Head-to-head: v1 vs v2 vs v3  (same {len(eligible)} patients)")
print(f"{'='*60}")

MODELS = {
    "v1": dict(intercept=0.356742,  log_psa=-0.017489, psad=None,
               pirads3=-0.061356, pirads4=0.967766, pirads5=1.255289, threshold=0.50),
    "v2": dict(intercept=-1.526236, log_psa=0.260607,  psad=None,
               pirads3=-1.200596, pirads4=0.424159, pirads5=0.792264, threshold=0.30),
    "v3": dict(intercept=intercept, log_psa=weights["logPSA"], psad=weights["PSAD"],
               pirads3=weights["pirads_3"], pirads4=weights["pirads_4"],
               pirads5=weights["pirads_5"], threshold=0.30),
}

def prob(m, psa, psad_val, pirads):
    lp = math.log(max(psa, 0.01))
    logit = (m["intercept"]
             + m["log_psa"] * lp
             + (m["psad"] * psad_val if m["psad"] is not None else 0)
             + m["pirads3"] * (1 if pirads==3 else 0)
             + m["pirads4"] * (1 if pirads==4 else 0)
             + m["pirads5"] * (1 if pirads==5 else 0))
    return 1 / (1 + math.exp(-logit))

hdr = f"  {'Metric':<28}  {'v1':>8}  {'v2':>8}  {'v3+PSAD':>8}"
print(hdr); print("  " + "─"*60)

for mname, m in MODELS.items():
    tp=fp=tn=fn=hg=0
    probs_m, acts = [], []
    for r in eligible:
        psa_v    = _f(r["psa"])
        psad_v   = _f(r["psad"])
        pirads_v = _i(r["pirads"])
        act      = _b(r["path_gg2_positive"])
        gg_max   = _i(r.get("path_gg_max"))
        p = prob(m, psa_v, psad_v if psad_v else 0, pirads_v)
        pred = p >= m["threshold"]
        probs_m.append(p); acts.append(act)
        if pred and act==1:     tp+=1
        elif pred and act==0:   fp+=1
        elif not pred and act==0: tn+=1
        else:
            fn+=1
            if gg_max is not None and gg_max >= 3: hg+=1
    pos_p = [p for p,a in zip(probs_m,acts) if a==1]
    neg_p = [p for p,a in zip(probs_m,acts) if a==0]
    conc  = sum(1 for p in pos_p for n in neg_p if p>n)
    tied  = sum(1 for p in pos_p for n in neg_p if p==n)
    auc_t = (conc+0.5*tied)/(len(pos_p)*len(neg_p))
    MODELS[mname]["_res"] = dict(tp=tp,fp=fp,tn=tn,fn=fn,hg=hg,
        sens=tp/(tp+fn) if (tp+fn) else 0,
        spec=tn/(tn+fp) if (tn+fp) else 0,
        ppv=tp/(tp+fp)  if (tp+fp) else 0,
        npv=tn/(tn+fn)  if (tn+fn) else 0, auc=auc_t)

rows_out = [
    ("AUC",           "auc",  "{:.3f}"),
    ("Sensitivity",   "sens", "{:.1%}"),
    ("Specificity",   "spec", "{:.1%}"),
    ("PPV",           "ppv",  "{:.1%}"),
    ("NPV",           "npv",  "{:.1%}"),
    ("TP",            "tp",   "{}"),
    ("FP",            "fp",   "{}"),
    ("TN",            "tn",   "{}"),
    ("FN",            "fn",   "{}"),
    ("HG (GG3+) miss","hg",   "{}"),
]
for label, key, fmt in rows_out:
    vals = {mn: MODELS[mn]["_res"][key] for mn in ["v1","v2","v3"]}
    best = ("v3" if key in ("auc","sens","spec","ppv","npv","tp","tn")
            else "v1") if False else None
    print(f"  {label:<28}  "
          f"{fmt.format(vals['v1']):>8}  "
          f"{fmt.format(vals['v2']):>8}  "
          f"{fmt.format(vals['v3']):>8}")

# ── P0131 specifically ───────────────────────────────────────────────────────
print(f"\n  P0131 (missed GG3 in v2) — PSA=2.4, PI-RADS=4, PSAD=?")
all_rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
p131 = next((r for r in all_rows if r["patient_id"]=="P0131"), None)
if p131:
    psa_v = _f(p131.get("psa")); psad_v = _f(p131.get("psad")); pr = _i(p131.get("pirads"))
    print(f"    PSA={psa_v}  PSAD={psad_v}  PI-RADS={pr}  GG={p131.get('path_gg_max')}")
    for mn, m in MODELS.items():
        p = prob(m, psa_v or 0, psad_v or 0, pr or 4)
        caught = "✓ CAUGHT" if p >= m["threshold"] else "✗ MISSED"
        print(f"    {mn}: P(GG≥2)={p:.1%}  threshold={m['threshold']:.0%}  → {caught}")

# ── Paste-ready coefficients ─────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  v3 coefficients — paste into model.py / calculatorConfig.js")
print(f"{'='*60}")
print(f"  intercept : {intercept:.6f}")
for fn, w in weights.items():
    print(f"  {fn:<12}: {w:.6f}")
print(f"  AUC OOF   : {auc_oof:.4f}")
print(f"  N         : {len(eligible)}")
print(f"  Prevalence: {100*pos/len(eligible):.1f}%")
print()
