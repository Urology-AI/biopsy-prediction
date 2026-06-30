"""
llm_extract.py — Local LLM field extraction for clinical notes.

Supports:
  - LM Studio  : http://localhost:1234/v1  (OpenAI-compatible)
  - Ollama     : http://localhost:11434/v1  (OpenAI-compatible endpoint)

Flow:
  1. OpenMed de-identifies text (done upstream in pipeline.py)
  2. Local LLM extracts structured fields as JSON
  3. Regex fallback fills any fields the LLM missed

Usage:
  from llm_extract import extract_with_llm, llm_available
  if llm_available():
      fields = extract_with_llm(deidentified_text)
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Optional

# ── Endpoint discovery ────────────────────────────────────────
_ENDPOINTS = [
    "http://localhost:1234/v1",   # LM Studio
    "http://localhost:11434/v1",  # Ollama (OpenAI-compat)
]

_SYSTEM_PROMPT = """You are a clinical data extraction assistant.
Extract structured data from the de-identified urology clinical note below.
Respond ONLY with a single JSON object — no explanation, no markdown, no extra text.

Required fields (use null if not found or unclear):
{
  "psa": <float ng/mL — most recent pre-biopsy PSA>,
  "pirads": <integer 1-5 — PI-RADS score from MRI>,
  "prostate_volume_cc": <float mL — prostate volume>,
  "psad": <float — PSA density, if explicitly stated>,
  "age": <integer — patient age in years>,
  "path_gg_max": <integer 0-5 — highest Grade Group on pathology; 0=benign; null=unknown>,
  "path_benign": <boolean — true if pathology is entirely benign/negative>,
  "path_gg2_positive": <boolean — true if any core is Grade Group 2 or higher>,
  "cribriform": <boolean — true if cribriform pattern mentioned>,
  "excluded": <boolean — true if patient had prior prostatectomy (S/P RALP) or this is a post-prostatectomy fossa biopsy>,
  "exclusion_reason": <string or null>
}

Rules:
- PSA: take the value closest to the biopsy date. Ignore PSA nadir or post-treatment PSA.
- PI-RADS: integer only (1-5). If a range like "4-5" is given, take the higher value.
- Grade Group: derive from Gleason score if needed (3+3=GG1, 3+4=GG2, 4+3=GG3, 4+4=GG4, 4+5 or 5+x=GG5).
- If pathology says "negative for tumor", "benign prostatic tissue", or "no carcinoma": path_benign=true, path_gg_max=0, path_gg2_positive=false.
- If pathology result is pending or not present: path_gg_max=null, path_gg2_positive=null.
- excluded=true ONLY for S/P RALP / post-prostatectomy patients.
"""


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _find_endpoint() -> Optional[str]:
    for base in _ENDPOINTS:
        try:
            req = urllib.request.Request(f"{base}/models", method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                body = json.loads(r.read())
                if body.get("data") or body.get("models"):
                    return base
        except Exception:
            continue
    return None


def llm_available() -> bool:
    return _find_endpoint() is not None


def _best_model(base: str) -> str:
    """Pick the first available model — prefer larger ones."""
    try:
        req = urllib.request.Request(f"{base}/models", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            body = json.loads(r.read())
            models = body.get("data") or body.get("models") or []
            ids = [m.get("id") or m.get("name", "") for m in models]
            # Prefer models with more parameters
            for preference in ["70b", "34b", "13b", "8b", "7b", "3b"]:
                for mid in ids:
                    if preference in mid.lower():
                        return mid
            return ids[0] if ids else "default"
    except Exception:
        return "default"


def extract_with_llm(text: str, verbose: bool = False) -> dict:
    """
    Extract clinical fields from de-identified text using a local LLM.
    Returns a dict with extracted fields. Falls back to empty dict on failure.
    """
    base = _find_endpoint()
    if base is None:
        return {}

    model = _best_model(base)
    if verbose:
        print(f"    [LLM] Using {base}  model={model}")

    # Truncate to ~3000 chars — enough for one patient note
    note = text[:3000].strip()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"Clinical note:\n\n{note}"},
        ],
        "temperature": 0.0,
        "max_tokens":  512,
    }

    try:
        resp    = _post_json(f"{base}/chat/completions", payload, timeout=90)
        content = resp["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if present
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        result = json.loads(content)
        if verbose:
            print(f"    [LLM] Extracted: {result}")
        return result

    except Exception as e:
        if verbose:
            print(f"    [LLM] Failed: {e}")
        return {}


def merge_llm_and_regex(llm: dict, regex: dict) -> dict:
    """
    Merge LLM extraction with regex extraction.
    LLM takes priority; regex fills gaps where LLM returned null.
    """
    merged = dict(regex)  # start with regex
    for key, val in llm.items():
        if val is not None and val != "":
            merged[key] = val  # LLM wins if it found something
    return merged


# ── Quick test ────────────────────────────────────────────────
if __name__ == "__main__":
    print("LLM available:", llm_available())
    if llm_available():
        sample = """
Type: AR, MRI guided TP prostate biopsy PSA 6.2
PSA: 6.2 ng/mL   PI-RADS: 5   Prostate volume: 53 cc
Pathology result: Prostatic adenocarcinoma, Gleason 7 (3+4), Grade Group 2
Cores positive: 3/12
Plan: Discuss treatment options
"""
        result = extract_with_llm(sample, verbose=True)
        print(json.dumps(result, indent=2))
    else:
        print("Start LM Studio or Ollama first.")
        print("  LM Studio: load a model and click 'Start Server'")
        print("  Ollama:    ollama serve")
