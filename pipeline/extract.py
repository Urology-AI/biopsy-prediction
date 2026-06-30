"""
extract.py — Read any clinical document (PDF, DOCX, TXT), split into
per-patient sections, de-identify with OpenMed, then extract structured
urological fields for the GG≥2 model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from openmed import deidentify
    OPENMED_AVAILABLE = True
except ImportError:
    OPENMED_AVAILABLE = False


# ---------------------------------------------------------------------------
# Document reading
# ---------------------------------------------------------------------------

def read_file(path: str | Path) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(p) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            import pypdf
            reader = pypdf.PdfReader(str(p))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix in (".docx", ".doc"):
        import docx
        doc = docx.Document(str(p))
        return "\n".join(para.text for para in doc.paragraphs)
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Multi-patient document splitter
# ---------------------------------------------------------------------------

# Patient record starts at a NAME/AGE/MRN header line OR a bare "Type:" line.
# We match either so that documents missing one or the other still split correctly.
_PATIENT_BOUNDARY = re.compile(
    r'(?:^|\n)'
    r'(?:'
    # "NAME / AGE / MRN" style header (any slash-separated tokens)
    r'[ \t]*(?:NAME|PATIENT)\b[^\n]*/[^\n]*'
    # OR a standalone "Type:" line (not preceded by non-whitespace on the same line)
    r'|[ \t]*Type\s*:[^\n]+'
    r')',
    re.IGNORECASE,
)

# Pathology section starts here
_PATH_ANCHOR = re.compile(
    r'(?:^|\n)[ \t]*(?:'
    r'Pathology\s+result'
    r'|Pathology:'
    r'|Biopsy\s+result'
    r'|Final\s+(?:diagnosis|pathology)'
    r'|Gleason\s+\d+\s*\(\d\+\d\)'
    r'|Benign\s+prostate\s+tissue'
    r')',
    re.IGNORECASE,
)

def _normalize_dates(text: str) -> str:
    """Normalize double-slash dates: '3//26' → '3/26'."""
    return re.sub(r'(\d{1,2})//(\d{2,4})', r'\1/\2', text)

def split_patients(text: str) -> list[str]:
    """
    Split a multi-patient document into individual patient sections.

    Tries two strategies in order:
    1. Split on NAME/AGE/MRN header lines (most reliable in DOCX exports).
    2. Fallback: split on standalone Type: lines.

    Returns a list of non-empty patient section strings.
    """
    text = _normalize_dates(text)

    # Strategy 1: NAME header boundaries
    name_boundaries = [
        m.start() for m in re.finditer(
            r'(?:^|\n)[ \t]*(?:NAME|PATIENT)\b[^\n]*/[^\n]*',
            text, re.IGNORECASE
        )
    ]
    # Strategy 2: Type: boundaries
    type_boundaries = [
        m.start() for m in re.finditer(
            r'(?:^|\n)[ \t]*Type\s*:[^\n]+',
            text, re.IGNORECASE
        )
    ]

    # Use NAME boundaries if found, otherwise Type: boundaries
    boundaries = name_boundaries if len(name_boundaries) > 1 else type_boundaries

    if not boundaries:
        return [text.strip()]

    # Slice text at each boundary; each slice is one patient record
    sections = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)

    return sections


def split_note_pathology(text: str) -> tuple[str, str]:
    """Split a single patient section into (clinical note, pathology result)."""
    m = _PATH_ANCHOR.search(text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    return text.strip(), ""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

EXCLUDED_TYPES = {
    "RALP", "S/P RALP", "POST-PROSTATECTOMY", "FOSSA", "CYSTECTOMY",
    "TURP", "POST PROSTATECTOMY",
}

@dataclass
class ClinicalFields:
    age: Optional[int] = None
    psa: Optional[float] = None
    psa_history: list[tuple[str, float]] = field(default_factory=list)
    pirads: Optional[int] = None
    pirads_source: str = ""
    pirads_date: str = ""
    prostate_volume_cc: Optional[float] = None
    psad: Optional[float] = None
    shim: Optional[int] = None
    ipss: Optional[int] = None
    bmi: Optional[float] = None
    prior_biopsy: Optional[bool] = None
    case_type: str = ""          # raw Type: value from note
    excluded: bool = False       # True for post-prostatectomy etc.
    exclusion_reason: str = ""
    case_id: str = ""
    raw_text: str = ""
    deidentified_text: str = ""
    extraction_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# De-identification
# ---------------------------------------------------------------------------

def deidentify_note(text: str) -> str:
    if not OPENMED_AVAILABLE:
        return text
    try:
        result = deidentify(text, method="mask", confidence_threshold=0.4)
        return result.deidentified_text
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_score(date_str: str) -> int:
    parts = date_str.strip().split("/")
    try:
        if len(parts) == 2:
            month, year = int(parts[0]), int(parts[1])
            year = 2000 + year if year < 100 else year
            return year * 100 + month
        if len(parts) == 3:
            month, _, year = int(parts[0]), int(parts[1]), int(parts[2])
            year = 2000 + year if year < 100 else year
            return year * 10000 + month * 100
    except ValueError:
        pass
    return 0


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def extract_fields(text: str, case_id: str = "", already_deidentified: bool = False) -> ClinicalFields:
    cf = ClinicalFields(case_id=case_id, raw_text=text)
    cf.deidentified_text = text if already_deidentified else deidentify_note(text)
    t = text

    # ── Case type ────────────────────────────────────────────────────────────
    type_m = re.search(r'Type\s*:\s*(.+)', t, re.IGNORECASE)
    if type_m:
        cf.case_type = type_m.group(1).strip()
        upper = cf.case_type.upper()
        for excl in EXCLUDED_TYPES:
            if excl in upper:
                cf.excluded = True
                cf.exclusion_reason = f"Post-procedure type: {cf.case_type}"
                return cf

    # ── Age — first standalone 2-digit number near top of note ───────────────
    age_m = re.search(
        r'(?:^|\n)\s*(\d{2})\s*(?:\n|,|\s+(?:year|yo|y\.o|M\b|F\b|Type))',
        t, re.IGNORECASE | re.MULTILINE
    )
    if age_m:
        cf.age = int(age_m.group(1))

    # ── PSA history ───────────────────────────────────────────────────────────
    psa_line_m = re.search(r'PSA\s*[:\s]\s*(.+)', t, re.IGNORECASE)
    if psa_line_m:
        psa_line = psa_line_m.group(1)
        pairs = re.findall(r'(\d+\.?\d*)\s*\((\d{1,2}/\d{2,4})\)', psa_line)
        if pairs:
            cf.psa_history = [(date, float(val)) for val, date in pairs]
            cf.psa_history.sort(key=lambda x: _date_score(x[0]), reverse=True)
            cf.psa = cf.psa_history[0][1]
        else:
            plain = re.search(r'(\d+\.?\d*)', psa_line)
            if plain:
                cf.psa = float(plain.group(1))

    # ── MRI blocks — dated, extract PI-RADS + volume ─────────────────────────
    mri_entries: list[tuple[int, Optional[int], Optional[float], str]] = []
    for mri_m in re.finditer(r'MRI\s+(\d{1,2}/\d{2,4})[^\n]*', t, re.IGNORECASE):
        date_str = mri_m.group(1)
        block = mri_m.group(0) + t[mri_m.end():mri_m.end() + 400].split('\n\n')[0]
        pr_m = re.search(r'PI[-\s]?RADS\s*[:\s]?\s*([1-5])', block, re.IGNORECASE)
        vol_m = re.search(r'(\d+)\s*(?:cc|mL)\b', block, re.IGNORECASE)
        mri_entries.append((
            _date_score(date_str),
            int(pr_m.group(1)) if pr_m else None,
            float(vol_m.group(1)) if vol_m else None,
            date_str,
        ))

    if mri_entries:
        mri_entries.sort(key=lambda x: x[0], reverse=True)
        cf.prostate_volume_cc = next((v for _, _, v, _ in mri_entries if v is not None), None)
        for _, pirads_val, _, date_str in mri_entries:
            if pirads_val is not None:
                cf.pirads = pirads_val
                cf.pirads_source = "MRI"
                cf.pirads_date = date_str
                break

    # Fallback: any PI-RADS mention
    if not cf.pirads:
        all_pirads = [int(m.group(1)) for m in re.finditer(
            r'PI[-\s]?RADS\s*[:\s]?\s*([1-5])', t, re.IGNORECASE
        )]
        if all_pirads:
            cf.pirads = max(all_pirads)
            cf.pirads_source = "MRI (date not parsed)"

    # PRIMUS fallback
    primus_vals = [int(m.group(1)) for m in re.finditer(r'PRIMUS\s*([1-5])', t, re.IGNORECASE)]
    if primus_vals and not cf.pirads:
        cf.pirads = max(primus_vals)
        cf.pirads_source = "PRIMUS (micro-ultrasound)"
        cf.extraction_notes.append("PI-RADS from PRIMUS — not MRI")

    # Volume fallback
    if not cf.prostate_volume_cc:
        vol_m = re.search(r'(\d{2,3})\s*(?:cc|mL)\b', t, re.IGNORECASE)
        if vol_m:
            cf.prostate_volume_cc = float(vol_m.group(1))

    # ── PSAD ─────────────────────────────────────────────────────────────────
    psad_m = re.search(r'\bPSAD\s*[:\s=]\s*(\d+\.?\d*)', t, re.IGNORECASE)
    if psad_m:
        cf.psad = float(psad_m.group(1))
    elif cf.psa and cf.prostate_volume_cc and cf.prostate_volume_cc > 0:
        cf.psad = round(cf.psa / cf.prostate_volume_cc, 4)

    # ── SHIM / IPSS / BMI ────────────────────────────────────────────────────
    for attr, pat in [("shim", r'\bSHIM\s*[:\s]\s*(\d+)'), ("ipss", r'\bIPSS\s*[:\s]\s*(\d+)')]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            setattr(cf, attr, int(m.group(1)))
    bmi_m = re.search(r'\bBMI\s*[:\s]\s*(\d+\.?\d*)', t, re.IGNORECASE)
    if bmi_m:
        cf.bmi = float(bmi_m.group(1))

    cf.prior_biopsy = bool(re.search(
        r'prior\s+biopsy|previous\s+biopsy|confirmatory\s+biopsy|Type:\s*AS\b',
        t, re.IGNORECASE
    ))

    return cf


# ---------------------------------------------------------------------------
# Pathology extraction
# ---------------------------------------------------------------------------

def _gleason_to_gg(a: int, b: int) -> int:
    total = a + b
    if total <= 6:                    return 1
    if total == 7 and a == 3:         return 2
    if total == 7 and a == 4:         return 3
    if total == 8:                    return 4
    return 5  # 9 or 10


def extract_pathology(text: str) -> dict:
    t = text

    # ── Benign / negative patterns ────────────────────────────
    benign = bool(re.search(
        r'benign\s+prostate'
        r'|no\s+(?:evidence\s+of\s+)?(?:carcinoma|malignancy|cancer|prostatic\s+adenocarcinoma)'
        r'|negative\s+for\s+(?:malignancy|carcinoma|cancer)'
        r'|prostatic\s+adenocarcinoma\s+not\s+identified'
        r'|no\s+prostatic\s+adenocarcinoma'
        r'|atypical\s+small\s+acinar\s+proliferation'   # ASAP — not cancer
        r'|high.grade\s+prostatic\s+intraepithelial'    # HGPIN only — not cancer
        , t, re.IGNORECASE
    ))

    gg_scores = []

    # ── 1. Explicit Grade Group label ─────────────────────────
    # "Grade Group 2", "GG2", "GG 2", "grade group: 2"
    for m in re.finditer(
        r'(?:grade\s+group|GG)\s*[:\-]?\s*([1-5])',
        t, re.IGNORECASE
    ):
        gg_scores.append(int(m.group(1)))

    # ── 2. Gleason (total) (a+b) — original pattern ──────────
    # "Gleason 7 (3+4)", "Gleason7 (3+4)", "Gleason score 7 (3+4)"
    for m in re.finditer(
        r'Gleason\s*(?:score\s*)?\d+\s*\((\d)\+(\d)\)',
        t, re.IGNORECASE
    ):
        gg_scores.append(_gleason_to_gg(int(m.group(1)), int(m.group(2))))

    # ── 3. Gleason (a+b) without total ───────────────────────
    # "Gleason 3+4", "Gleason6(3+3)", "Gleason score: 3+4 = 7"
    for m in re.finditer(
        r'Gleason\s*(?:score\s*[:\-]?\s*)?(\d)\s*\+\s*(\d)(?!\s*\))',
        t, re.IGNORECASE
    ):
        gg_scores.append(_gleason_to_gg(int(m.group(1)), int(m.group(2))))

    # ── 4. Gleason = total only ───────────────────────────────
    # "Gleason 6", "Gleason score 9" — less precise, only use if nothing else found
    if not gg_scores:
        for m in re.finditer(r'Gleason\s+(?:score\s*[:\-]?\s*)?([6-9]|10)\b', t, re.IGNORECASE):
            total = int(m.group(1))
            if total <= 6:   gg_scores.append(1)
            elif total == 7: gg_scores.append(2)   # assume 3+4 (conservative)
            elif total == 8: gg_scores.append(4)
            else:            gg_scores.append(5)

    # ── 5. Adenocarcinoma present but no grade ────────────────
    has_cancer = bool(re.search(r'prostatic\s+adenocarcinoma|prostate\s+cancer', t, re.IGNORECASE))

    # Deduplicate and compute max
    gg_scores = sorted(set(gg_scores))
    gg_max = max(gg_scores) if gg_scores else (0 if benign else None)

    return {
        "gg_max":         gg_max,
        "benign":         benign and not gg_scores,
        "gleason_scores": gg_scores,
        "cribriform":     bool(re.search(r'cribriform', t, re.IGNORECASE)),
        "gg2_positive":   (gg_max is not None and gg_max >= 2),
    }
