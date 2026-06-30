"""
FastAPI server for ePSA GG≥2 biopsy prediction model (v3).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "model"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

import model as m

app = FastAPI(title="ePSA Biopsy Prediction", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


class PredictRequest(BaseModel):
    psa: float = Field(..., gt=0, description="PSA in ng/mL")
    pirads: int = Field(..., ge=1, le=5, description="PI-RADS score 1–5")
    prostate_volume: Optional[float] = Field(None, gt=0, description="Prostate volume in mL (optional)")


class PredictResponse(BaseModel):
    prob: float
    percent: float
    interpretation: str
    guideline_rate: str
    reliable: bool
    psad: Optional[float]
    psad_tier: Optional[str]
    model_version: str
    threshold: float


@app.get("/")
def index():
    return FileResponse(str(frontend_dir / "index.html"))


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    psad = None
    if req.prostate_volume and req.prostate_volume > 0:
        psad = req.psa / req.prostate_volume

    result = m.predict(pirads=req.pirads, psa=req.psa, psad=psad)

    model_version = "v3 (PSA + PSAD + PI-RADS)" if psad is not None else "v2 fallback (PSA + PI-RADS)"

    return PredictResponse(
        prob=result.prob,
        percent=result.percent,
        interpretation=result.interpretation,
        guideline_rate=result.guideline_rate,
        reliable=result.reliable,
        psad=round(psad, 3) if psad else None,
        psad_tier=result.psad_tier,
        model_version=model_version,
        threshold=m.THRESHOLD,
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": "ePSA v3", "auc_oof": 0.7025}
