"""
model.py — GG≥2 logistic regression, ePSA Model v4.

v4: N=126, Mount Sinai biopsy registry, 39.7% GG≥2 prevalence.
    AUC OOF: 0.7389 (5-fold CV × 100 repeats, properly averaged per repeat),
    retrained 2026-07-02.
    Predictors: logPSA + logVolume + PI-RADS dummies (ref: PI-RADS 1–2).
    PSAD was dropped: PSAD = PSA/volume, so fitting logPSA + PSAD + logVolume
    together makes the three terms share variance and their individual
    coefficients flip sign / lose clinical meaning (confirmed by ablation —
    see model/train_v3.py history). logVolume alone is both cleaner and
    scored fractionally higher OOF AUC than the 3-continuous-predictor
    version (0.7389 vs 0.7360), so v4 uses logPSA + logVolume, no PSAD term.
    Threshold: 0.25 (94% sensitivity, 34% specificity, NPV 90% at this
    prevalence). See THRESHOLD comment below for how this was chosen —
    AUA/SUO 2026 does NOT specify a numeric NPV/sensitivity cutoff for
    biopsy-deferral tools (confirmed against the guideline text directly,
    2026-07-02); it explicitly leaves "sufficiently low risk" undefined and
    delegates to shared decision-making (Statement 11). 0.25 was chosen to
    match, not exceed, the two concrete performance benchmarks the guideline
    itself does cite (see THRESHOLD below) — it is a literature anchor, not
    an AUA mandate, and should be revisited with a clinician before this
    tool is used to actually defer biopsies.

    Validation (2026-07-02, N=126 unless noted):
    - AUC point estimate 0.746 (avg-OOF-prob scoring); bootstrap 95% CI
      [0.65, 0.83] over 5000 patient-level resamples. The CV-repeat sd
      (0.012, above) measures fold-assignment noise only — the bootstrap CI
      is the real answer to "how much do we trust the 0.74 number." At this
      sample size, true AUC could plausibly be anywhere in that 18-point
      range; treat 0.74 as a point estimate, not a precise one.
    - Calibration: 5-bin decile table shows predicted vs. observed risk in
      close agreement and monotonic (e.g. lowest bin 16.8% predicted / 11.5%
      observed, highest bin 64.3% predicted / 72.0% observed).
      Hosmer-Lemeshow-style chi2=1.99 (df=3) shows no evidence of
      miscalibration. Brier score 0.1995 vs. 0.2394 naive-prevalence
      baseline. So predicted probabilities are usable as probabilities, not
      just a ranking score.
    - Temporal hold-out (closest available proxy for external validation —
      no separate-site cohort exists yet): fit on the earliest 81 patients
      by biopsy date (Nov 2024-Dec 2025), tested on the most recent 45
      (Dec 2025-May 2026) never seen during that fit. AUC 0.771 — no
      degradation vs. the CV estimate, so the model generalizes forward in
      time at this site. This does NOT establish that it transfers to a
      different site or population; only that it's stable over time here.

v3 (prior): N=120, AUC OOF 0.7025, logPSA + PSAD + PI-RADS, 2026-06-30.
v2 (prior): N=121, 28.9% prevalence, AUC OOF 0.670, no PSAD, 2026-06-29.
v1 (prior): N=96,  74.0% prevalence, AUC OOF 0.591, no PSAD, 2026-06-02.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# AUA 2026 Table 5 population-level GG≥2 detection rates by PI-RADS
# (pooled 23 studies; AUA/SUO EDPC 2026 p.21)
GUIDELINE_RATES = {
    1: "7% (95%CI 4–11%)",
    2: "7% (95%CI 4–11%)",
    3: "11% (95%CI 8–14%)",
    4: "37% (95%CI 33–40%)",
    5: "70% (95%CI 62–79%)",
}

RELIABLE_PIRADS = {4, 5}

# v4 decision threshold — literature-anchored, not an AUA-mandated cutoff.
#
# AUA/SUO 2026 EDPC guideline does not set a numeric NPV/sensitivity target for
# biopsy-deferral tools (Statement 11 leaves "sufficiently low risk" undefined
# and defers to shared decision-making). The two closest anchors the
# guideline itself provides:
#   (a) negative MRI (PI-RADS 1-2) NPV for GG>=2 = 91% (42-study pooled
#       systematic review, guideline Part II)
#   (b) adjunctive-biomarker triage tradeoff: 35% biopsy reduction at a cost
#       of missing 9% of clinically significant cancers (guideline Part II,
#       Statement 17 discussion)
# At threshold=0.30, this model's OOF performance (86% sens / 40% spec / 81%
# NPV) falls well short of both anchors — using it to defer biopsy would be
# a worse safety margin than a negative MRI alone. Threshold=0.25 (94% sens /
# 34% spec / 90% NPV) matches both anchors closely: ~6% missed cancers vs.
# the guideline's 9% biomarker benchmark, ~34% biopsies avoided vs. 35%, and
# NPV of 90% vs. the 91% negative-MRI benchmark.
THRESHOLD = 0.25


@dataclass
class ModelResult:
    pirads: int
    psa: float
    prob: float
    percent: float
    interpretation: str
    guideline_rate: str
    reliable: bool
    psad: Optional[float] = None
    psad_tier: Optional[str] = None
    prostate_volume_cc: Optional[float] = None


def predict(
    pirads: int,
    psa: float,
    psad: Optional[float] = None,
    prostate_volume_cc: Optional[float] = None,
) -> Optional[ModelResult]:
    """
    Predict P(GG≥2) — ePSA Model v4 (logPSA + logVolume + PI-RADS dummies).

    logit(GG≥2) =  0.928327
                +   0.234065  × ln(PSA)
                + (−0.693935) × ln(prostate_volume_cc)
                + (−0.274166) × [PIRADS=3]
                +   0.953916  × [PIRADS=4]
                +   1.898259  × [PIRADS=5]

    N=126, AUC OOF=0.7389, prevalence=39.7%, retrained 2026-07-02.
    PSAD is intentionally not in the logit (see module docstring — it's
    collinear with logPSA/logVolume and its coefficient isn't independently
    interpretable when fit alongside them). `psad` is still accepted for
    the informational psad_tier field only.

    If prostate_volume_cc is None, falls back to v3 (logPSA + PSAD +
    PI-RADS) when psad is given, or v2 (logPSA + PI-RADS only) otherwise.
    """
    if pirads is None or psa is None:
        return None
    if pirads not in [1, 2, 3, 4, 5]:
        return None
    if psa <= 0:
        return None
    if prostate_volume_cc is not None and prostate_volume_cc <= 0:
        return None

    pirads3 = 1 if pirads == 3 else 0
    pirads4 = 1 if pirads == 4 else 0
    pirads5 = 1 if pirads == 5 else 0
    log_psa = math.log(max(psa, 0.01))

    if prostate_volume_cc is not None:
        # v4 — logPSA + logVolume + PI-RADS
        log_vol = math.log(max(prostate_volume_cc, 1.0))
        logit = (
            0.928327
            +  0.234065  * log_psa
            + (-0.693935) * log_vol
            + (-0.274166) * pirads3
            +  0.953916   * pirads4
            +  1.898259   * pirads5
        )
    elif psad is not None:
        # v3 fallback — logPSA + PSAD + PI-RADS (volume unavailable)
        logit = (
            -1.485772
            +  0.145017  * log_psa
            +  0.942349  * psad
            + (-1.181514) * pirads3
            +  0.468079   * pirads4
            +  0.735267   * pirads5
        )
    else:
        # v2 fallback when neither volume nor PSAD is available
        logit = (
            -1.526236
            +  0.260607  * log_psa
            + (-1.200596) * pirads3
            +  0.424159   * pirads4
            +  0.792264   * pirads5
        )

    prob    = 1 / (1 + math.exp(-logit))
    percent = round(prob * 1000) / 10

    # Bands calibrated to 39.7% GG≥2 prevalence, anchored to THRESHOLD (0.25)
    if prob < 0.15:
        interpretation = "Low GG≥2 risk"
    elif prob < THRESHOLD:
        interpretation = "Below-average GG≥2 risk"
    elif prob < 0.45:
        interpretation = "Intermediate GG≥2 risk — biopsy recommended"
    else:
        interpretation = "Elevated GG≥2 risk — biopsy strongly recommended"

    # PSAD tier (AUA 2026 Statement 16) — informational only, not used in logit
    psad_tier = None
    if psad is not None:
        if psad < 0.10:
            psad_tier = "Low (<0.10) — biopsy may be deferred (NPV 94%)"
        elif psad < 0.15:
            psad_tier = "Borderline (0.10–0.15)"
        else:
            psad_tier = "Elevated (≥0.15) — supports biopsy"

    return ModelResult(
        pirads=pirads,
        psa=psa,
        prob=prob,
        percent=percent,
        interpretation=interpretation,
        guideline_rate=GUIDELINE_RATES.get(pirads, "—"),
        reliable=pirads in RELIABLE_PIRADS,
        psad=psad,
        psad_tier=psad_tier,
        prostate_volume_cc=prostate_volume_cc,
    )
