"""
test_model.py — sanity/regression tests for model.py (ePSA Model v4).

Run: python3 model/test_model.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from model import predict, THRESHOLD, GUIDELINE_RATES, RELIABLE_PIRADS

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== Input validation / edge cases ==")

check("None pirads returns None", predict(None, 5.0) is None)
check("None psa returns None", predict(3, None) is None)
check("pirads out of range (0) returns None", predict(0, 5.0) is None)
check("pirads out of range (6) returns None", predict(6, 5.0) is None)
check("psa <= 0 returns None", predict(3, 0) is None)
check("negative psa returns None", predict(3, -1.0) is None)
check("volume <= 0 returns None", predict(3, 5.0, prostate_volume_cc=0) is None)
check("negative volume returns None", predict(3, 5.0, prostate_volume_cc=-10) is None)

print("\n== v4 path (volume provided) is selected and monotonic ==")

r_v4 = predict(pirads=4, psa=6.0, prostate_volume_cc=40.0)
check("v4 result populated", r_v4 is not None)
check("v4 echoes prostate_volume_cc", r_v4.prostate_volume_cc == 40.0)

# larger volume -> lower risk (v4 logVolume coefficient is negative)
small_vol = predict(pirads=4, psa=6.0, prostate_volume_cc=20.0)
large_vol = predict(pirads=4, psa=6.0, prostate_volume_cc=80.0)
check(
    "risk decreases as prostate volume increases (fixed PSA/PIRADS)",
    small_vol.prob > large_vol.prob,
    f"small_vol={small_vol.prob:.4f} large_vol={large_vol.prob:.4f}",
)

# higher PSA -> higher risk, holding volume/pirads fixed
low_psa = predict(pirads=4, psa=3.0, prostate_volume_cc=40.0)
high_psa = predict(pirads=4, psa=15.0, prostate_volume_cc=40.0)
check(
    "risk increases with PSA (fixed volume/PIRADS)",
    high_psa.prob > low_psa.prob,
    f"low={low_psa.prob:.4f} high={high_psa.prob:.4f}",
)

# PI-RADS 5 > PI-RADS 4 > PI-RADS 1/2 risk, holding PSA/volume fixed
p12 = predict(pirads=2, psa=6.0, prostate_volume_cc=40.0)
p4  = predict(pirads=4, psa=6.0, prostate_volume_cc=40.0)
p5  = predict(pirads=5, psa=6.0, prostate_volume_cc=40.0)
check("PI-RADS 5 risk > PI-RADS 4 risk", p5.prob > p4.prob, f"{p5.prob:.4f} vs {p4.prob:.4f}")
check("PI-RADS 4 risk > PI-RADS 1-2 risk", p4.prob > p12.prob, f"{p4.prob:.4f} vs {p12.prob:.4f}")

print("\n== Fallback chain ==")

r_v3 = predict(pirads=4, psa=6.0, psad=0.15)  # no volume -> v3 fallback
check("no volume + psad given -> falls back (not v4, uses psad path)", r_v3 is not None)
check("v3 fallback result has psad set", r_v3.psad == 0.15)
check("v3 fallback result has no volume", r_v3.prostate_volume_cc is None)

r_v2 = predict(pirads=4, psa=6.0)  # neither volume nor psad
check("no volume, no psad -> v2 fallback works", r_v2 is not None)
check("v2 fallback has no psad/volume", r_v2.psad is None and r_v2.prostate_volume_cc is None)

# all three paths should give different (non-degenerate) probabilities for the same PSA/PIRADS
check(
    "v4/v3/v2 give distinct probabilities for same PSA+PIRADS (different models)",
    len({round(r_v4.prob, 3), round(r_v3.prob, 3), round(r_v2.prob, 3)}) >= 2,
    f"v4={r_v4.prob:.4f} v3={r_v3.prob:.4f} v2={r_v2.prob:.4f}",
)

print("\n== PSAD tier is informational-only (independent of prediction path) ==")

r_hi_psad = predict(pirads=3, psa=6.0, psad=0.20, prostate_volume_cc=40.0)
check("psad_tier computed even when v4 path used (psad ignored in logit)", r_hi_psad.psad_tier is not None)
check("elevated psad tier text", "Elevated" in r_hi_psad.psad_tier, r_hi_psad.psad_tier)

r_lo_psad = predict(pirads=3, psa=6.0, psad=0.05, prostate_volume_cc=40.0)
check("low psad tier text", "Low" in r_lo_psad.psad_tier, r_lo_psad.psad_tier)

# and confirm the v4 logit really doesn't depend on psad's value
r_psad_a = predict(pirads=3, psa=6.0, psad=0.05, prostate_volume_cc=40.0)
r_psad_b = predict(pirads=3, psa=6.0, psad=0.30, prostate_volume_cc=40.0)
check(
    "v4 probability unaffected by psad value when volume is present",
    math.isclose(r_psad_a.prob, r_psad_b.prob, rel_tol=1e-9),
    f"{r_psad_a.prob} vs {r_psad_b.prob}",
)

print("\n== Metadata / labels ==")

check("guideline_rate present for all pirads 1-5",
      all(predict(p, 5.0, prostate_volume_cc=40).guideline_rate == GUIDELINE_RATES[p] for p in range(1, 6)))
check("reliable flag true only for pirads 4/5",
      all((predict(p, 5.0, prostate_volume_cc=40).reliable == (p in RELIABLE_PIRADS)) for p in range(1, 6)))
check("percent is prob*100 rounded to 1 decimal",
      math.isclose(r_v4.percent, round(r_v4.prob * 1000) / 10))
check("THRESHOLD constant is 0.25 (literature-anchored, see model.py)", THRESHOLD == 0.25)

print("\n== Known coefficient sanity check (hand-computed) ==")

# hand-compute logit for pirads=4, psa=6.0, vol=40.0 using the v4 formula in the docstring
expected_logit = (
    0.928327
    + 0.234065 * math.log(6.0)
    + (-0.693935) * math.log(40.0)
    + 0.953916  # pirads_4
)
expected_prob = 1 / (1 + math.exp(-expected_logit))
check(
    "predict() matches hand-computed v4 logit for a known input",
    math.isclose(r_v4.prob, expected_prob, rel_tol=1e-6),
    f"predict()={r_v4.prob} expected={expected_prob}",
)

print(f"\n{'='*50}")
if failures:
    print(f"  {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")
sys.exit(0)
