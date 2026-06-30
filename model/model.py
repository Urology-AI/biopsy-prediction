"""
model.py — GG≥2 logistic regression, ePSA Model v3.

v3: N=120, Mount Sinai biopsy registry, 29.2% GG≥2 prevalence.
    AUC OOF: 0.7025 (5-fold CV × 100 repeats), retrained 2026-06-30.
    Predictors: logPSA + PSAD + PI-RADS dummies (ref: PI-RADS 1–2).
    Threshold: 0.30 (OOF-optimal; 94% sensitivity, 41% specificity).

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

# v3 decision threshold (OOF-optimal at 29.2% prevalence)
THRESHOLD = 0.30


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


def predict(pirads: int, psa: float, psad: Optional[float] = None) -> Optional[ModelResult]:
    """
    Predict P(GG≥2) — ePSA Model v3 (logPSA + PSAD + PI-RADS dummies).

    logit(GG≥2) = −1.485772
                +   0.145017  × ln(PSA)
                +   0.942349  × PSAD
                + (−1.181514) × [PIRADS=3]
                +   0.468079  × [PIRADS=4]
                +   0.735267  × [PIRADS=5]

    N=120, AUC OOF=0.7025, prevalence=29.2%, retrained 2026-06-30.
    If PSAD is None, falls back to v2 equation (logPSA + PI-RADS only).
    """
    if pirads is None or psa is None:
        return None
    if pirads not in [1, 2, 3, 4, 5]:
        return None
    if psa <= 0:
        return None

    pirads3 = 1 if pirads == 3 else 0
    pirads4 = 1 if pirads == 4 else 0
    pirads5 = 1 if pirads == 5 else 0
    log_psa = math.log(max(psa, 0.01))

    if psad is not None:
        # v3 — full model with PSAD
        logit = (
            -1.485772
            +  0.145017  * log_psa
            +  0.942349  * psad
            + (-1.181514) * pirads3
            +  0.468079   * pirads4
            +  0.735267   * pirads5
        )
    else:
        # v2 fallback when PSAD unavailable
        logit = (
            -1.526236
            +  0.260607  * log_psa
            + (-1.200596) * pirads3
            +  0.424159   * pirads4
            +  0.792264   * pirads5
        )

    prob    = 1 / (1 + math.exp(-logit))
    percent = round(prob * 1000) / 10

    # Thresholds calibrated to 29.2% GG≥2 prevalence
    if prob < 0.20:
        interpretation = "Low GG≥2 risk"
    elif prob < 0.30:
        interpretation = "Below-average GG≥2 risk"
    elif prob < 0.45:
        interpretation = "Intermediate GG≥2 risk — biopsy recommended"
    else:
        interpretation = "Elevated GG≥2 risk — biopsy strongly recommended"

    # PSAD tier (AUA 2026 Statement 16)
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
    )
