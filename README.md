# biopsy-prediction

GG≥2 prostate cancer prediction model (ePSA Model v3) with a web interface for clinical decision support.

## Model

Logistic regression trained on N=120 biopsy-registry patients.  
Predictors: log(PSA) + PSAD + PI-RADS dummies (ref: PI-RADS 1–2).  
OOF AUC: 0.703 (5-fold × 100 repeats). Threshold: 0.30. Prevalence: 29.2% GG≥2.

When prostate volume is unavailable, falls back to v2 (PSA + PI-RADS only, AUC 0.670).

## Running

```bash
pip install -r requirements.txt
uvicorn api.server:app --reload
```

Then open http://localhost:8000.

## Structure

```
model/      — prediction logic, training script, model comparison
training/   — refit script (refit_part2_cancer_model.py)
api/        — FastAPI server (POST /predict)
frontend/   — single-page HTML form
```

## Disclaimer

For clinical decision support only. Not a replacement for physician judgment.  
Independent prospective validation is underway (ePSA-VALIDATE).
