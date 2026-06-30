# biopsy-prediction

GG≥2 prostate cancer prediction model (ePSA Model v3) with a web interface for clinical decision support.

## Model

Logistic regression trained on N=120 Mount Sinai biopsy-registry patients (2026 cohort).  
Predictors: log(PSA) + PSAD + PI-RADS dummies (ref: PI-RADS 1–2).  
OOF AUC: 0.703 (5-fold × 100 repeats). Threshold: 0.30. Prevalence: 29.2% GG≥2.

When prostate volume is unavailable, falls back to v2 (PSA + PI-RADS only, AUC 0.670).

> **Validation status:** The 2026 biopsy registry cohort (N=120) is the **training dataset**.
> OOF AUC is an honest within-sample estimate but is not independent validation.
> Coefficients are now frozen. The next prospective cohort will serve as true independent
> validation (ePSA-VALIDATE). Do not retrain on validation data.

## Running

```bash
pip install -r requirements.txt

# API
uvicorn api.server:app --reload

# Pipeline (extract → de-identify → predict)
cd pipeline
python3 pipeline.py run-all --dir /path/to/docx/folder
```

## Structure

```
model/      — v3 prediction logic, training script, model comparison
training/   — refit script (refit_part2_cancer_model.py)
pipeline/   — 3-stage CLI: extract → OpenMed de-identify → predict
api/        — FastAPI server (POST /predict)
frontend-react/ — React playground (GitHub Pages)
```

## Data & validation roadmap

| Cohort | N | Role | Status |
|---|---|---|---|
| Mount Sinai biopsy registry 2026 | 120 | Training | Complete — coefficients frozen |
| ePSA-VALIDATE (prospective) | TBD | Independent validation | Pending |

## Disclaimer

For clinical decision support only. Not a replacement for physician judgment.
