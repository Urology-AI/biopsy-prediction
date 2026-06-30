"""
pipeline.py — Three-stage validation pipeline:

  Stage 1 — extract:  Parse all documents → structured patient rows + pathology
  Stage 2 — deident:  Strip PII with OpenMed → safe to store / share
  Stage 3 — predict:  Run GG>=2 logistic regression → compare to actual outcome

Usage:
  python pipeline.py extract  --dir /path/to/docs  --out results/extracted.csv
  python pipeline.py deident  --in  results/extracted.csv
  python pipeline.py predict  --in  results/extracted.csv
  python pipeline.py run-all  --dir /path/to/docs          # all three in sequence
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Allow imports from repo root (model/) when running pipeline/ directly
sys.path.insert(0, str(Path(__file__).parent.parent / "model"))

from rich.console import Console
from rich.table import Table
from rich import box

from extract import (
    read_file, split_patients, split_note_pathology,
    extract_fields, extract_pathology, deidentify_note,
)
from model import predict
from llm_extract import extract_with_llm, merge_llm_and_regex, llm_available

console = Console()
_USE_LLM = llm_available()
if _USE_LLM:
    console.print("[green]✓ Local LLM detected — will use for field extraction[/green]")
else:
    console.print("[yellow]⚠ No local LLM found — using regex only. Start LM Studio or Ollama to enable LLM extraction.[/yellow]")

EXTRACTED_FIELDS = [
    "patient_id",
    "source_file",
    "case_type",
    "excluded",
    "exclusion_reason",
    # Clinical fields
    "age",
    "psa",
    "psa_history",       # JSON list of [date, value]
    "pirads",
    "pirads_source",
    "pirads_date",
    "prostate_volume_cc",
    "psad",
    "shim",
    "ipss",
    "bmi",
    "prior_biopsy",
    # Pathology
    "path_gg_max",
    "path_benign",
    "path_cribriform",
    "path_gleason_scores",  # JSON list
    "path_gg2_positive",
    "path_text_raw",
    # Model outputs (filled in stage 3)
    "predicted_prob",
    "predicted_gg2_pos",
    "model_reliable",
    "correct",
    # Audit
    "extraction_notes",
    "deidentified",
]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Extract
# ─────────────────────────────────────────────────────────────────────────────

def _deidentify_text(text: str) -> str:
    """De-identify a block of text with OpenMed. Falls back to original if unavailable."""
    try:
        from openmed import deidentify as _deident
        result = _deident(text, method="mask", confidence_threshold=0.4)
        return result.deidentified_text
    except Exception:
        return text


def stage_extract(docs_dir: str, out_csv: str) -> list[dict]:
    docs_path = Path(docs_dir)
    SUPPORTED = {".txt", ".pdf", ".docx", ".doc"}

    if docs_path.is_file():
        all_files = [docs_path]
    else:
        all_files = sorted(
            f for f in docs_path.iterdir()
            if f.suffix.lower() in SUPPORTED and ".path." not in f.name
        )

    console.print(f"\n[bold]Stage 1 — Extract[/bold]  ({len(all_files)} file(s))\n")

    rows: list[dict] = []
    patient_counter = 0

    for doc_file in all_files:
        console.print(f"  Reading [cyan]{doc_file.name}[/cyan]...")
        try:
            raw_text = read_file(doc_file)
        except Exception as e:
            console.print(f"    [red]Could not read: {e}[/red]")
            continue

        # Split on raw text so boundary markers (NAME/Type:) survive PII masking
        patient_sections = split_patients(raw_text)
        console.print(f"    → {len(patient_sections)} patient section(s)")

        # Sidecar pathology file (optional)
        sidecar = next(
            (doc_file.parent / f"{doc_file.stem}.path{s}"
             for s in [".txt", ".pdf", ".docx"]
             if (doc_file.parent / f"{doc_file.stem}.path{s}").exists()),
            None,
        )

        for i, section in enumerate(patient_sections, 1):
            patient_counter += 1
            patient_id = f"P{patient_counter:04d}"

            note_raw, path_raw = split_note_pathology(section)

            # Sidecar overrides embedded pathology for single-patient files
            if sidecar and len(patient_sections) == 1:
                try:
                    path_raw = read_file(sidecar)
                except Exception:
                    pass

            # De-identify each section separately before any field extraction
            console.print(f"    {patient_id}: De-identifying...")
            note_text = _deidentify_text(note_raw)
            path_text = _deidentify_text(path_raw) if path_raw else ""

            # extract_fields operates on already-de-identified text
            cf = extract_fields(note_text, case_id=patient_id, already_deidentified=True)
            path = extract_pathology(path_text) if path_text else {
                "gg_max": None, "benign": None, "cribriform": False,
                "gleason_scores": [], "gg2_positive": None,
            }

            # LLM extraction — runs on full de-identified note, fills gaps left by regex
            if _USE_LLM:
                full_text = note_text + ("\n" + path_text if path_text else "")
                llm = extract_with_llm(full_text)

                # Fill clinical fields regex missed
                if llm.get("psa") is not None and cf.psa is None:
                    cf.psa = llm["psa"]
                if llm.get("pirads") is not None and cf.pirads is None:
                    cf.pirads = llm["pirads"]
                if llm.get("prostate_volume_cc") is not None and cf.prostate_volume_cc is None:
                    cf.prostate_volume_cc = llm["prostate_volume_cc"]
                    if cf.psa and cf.prostate_volume_cc:
                        cf.psad = round(cf.psa / cf.prostate_volume_cc, 4)
                if llm.get("age") is not None and cf.age is None:
                    cf.age = llm["age"]
                if llm.get("excluded") and not cf.excluded:
                    cf.excluded = True
                    cf.exclusion_reason = llm.get("exclusion_reason", "LLM-flagged")

                # Fill pathology fields regex missed
                if llm.get("path_gg_max") is not None and path["gg_max"] is None:
                    path["gg_max"]      = llm["path_gg_max"]
                    path["gg2_positive"]= llm.get("path_gg2_positive", llm["path_gg_max"] >= 2)
                if llm.get("path_benign") is not None and path["benign"] is None:
                    path["benign"] = llm["path_benign"]
                if llm.get("cribriform") and not path["cribriform"]:
                    path["cribriform"] = llm["cribriform"]

            row = {
                "patient_id":        patient_id,
                "source_file":       doc_file.name,
                "case_type":         cf.case_type,
                "excluded":          cf.excluded,
                "exclusion_reason":  cf.exclusion_reason,
                "age":               cf.age,
                "psa":               cf.psa,
                "psa_history":       json.dumps(cf.psa_history),
                "pirads":            cf.pirads,
                "pirads_source":     cf.pirads_source,
                "pirads_date":       cf.pirads_date,
                "prostate_volume_cc": cf.prostate_volume_cc,
                "psad":              cf.psad,
                "shim":              cf.shim,
                "ipss":              cf.ipss,
                "bmi":               cf.bmi,
                "prior_biopsy":      cf.prior_biopsy,
                "path_gg_max":       path["gg_max"],
                "path_benign":       path["benign"],
                "path_cribriform":   path["cribriform"],
                "path_gleason_scores": json.dumps(path["gleason_scores"]),
                "path_gg2_positive": path["gg2_positive"],
                "path_text_raw":     path_text[:500] if path_text else "",
                "predicted_prob":    None,
                "predicted_gg2_pos": None,
                "model_reliable":    None,
                "correct":           None,
                "extraction_notes":  "; ".join(cf.extraction_notes),
                "deidentified":      True,
            }
            rows.append(row)

            status = "[yellow]EXCLUDED[/yellow]" if cf.excluded else (
                f"PSA={cf.psa}  PI-RADS={cf.pirads}  "
                f"Vol={cf.prostate_volume_cc}cc  "
                f"Path={'GG'+str(path['gg_max']) if path['gg_max'] is not None else ('Benign' if path['benign'] else 'MISSING')}"
            )
            console.print(f"    {patient_id}: {status}")

    _write_csv(rows, out_csv)
    console.print(f"\n  [green]Extracted {len(rows)} patients → {out_csv}[/green]")
    _print_extraction_table(rows)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — De-identify
# ─────────────────────────────────────────────────────────────────────────────

def stage_deidentify(csv_path: str) -> list[dict]:
    """Stage 2 is now a no-op: de-identification happens in stage 1 before any parsing.
    Kept for CLI completeness and to mark rows as confirmed de-identified."""
    rows = _read_csv(csv_path)
    console.print(f"\n[bold]Stage 2 — De-identify[/bold]  (already done in Stage 1)\n")
    already = sum(1 for r in rows if str(r.get("deidentified")).lower() == "true")
    console.print(f"  [green]{already}/{len(rows)} rows de-identified by OpenMed before extraction.[/green]\n")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Predict
# ─────────────────────────────────────────────────────────────────────────────

def stage_predict(csv_path: str) -> list[dict]:
    rows = _read_csv(csv_path)
    console.print(f"\n[bold]Stage 3 — Logistic Regression[/bold]  ({len(rows)} rows)\n")

    eligible = [r for r in rows if r.get("excluded") not in (True, "True")]
    excluded = len(rows) - len(eligible)
    if excluded:
        console.print(f"  Skipping {excluded} excluded patient(s) (post-prostatectomy etc.)\n")

    for row in eligible:
        pirads = _int(row.get("pirads"))
        psa    = _float(row.get("psa"))
        psad   = _float(row.get("psad"))

        if pirads is None or psa is None:
            row["predicted_prob"]    = None
            row["predicted_gg2_pos"] = None
            row["model_reliable"]    = None
            row["correct"]           = None
            console.print(f"  {row['patient_id']}: [yellow]Cannot predict — missing PSA or PI-RADS[/yellow]")
            continue

        result = predict(pirads, psa, psad)
        actual = _bool(row.get("path_gg2_positive"))

        row["predicted_prob"]    = round(result.prob, 4)
        # v2 model threshold=0.30 (OOF-optimal for 28.9% prevalence; 91% sensitivity)
        THRESHOLD = 0.30
        row["predicted_gg2_pos"] = result.prob >= THRESHOLD
        row["model_reliable"]    = result.reliable
        row["correct"]           = (result.prob >= THRESHOLD) == actual if actual is not None else None

        reliable_flag = "" if result.reliable else " [yellow]⚠ unreliable (PI-RADS≤3)[/yellow]"
        correct_flag  = (
            "[green]✓[/green]" if row["correct"] is True else
            "[red]✗[/red]"     if row["correct"] is False else
            "[dim]?[/dim]"
        )
        console.print(
            f"  {row['patient_id']}: "
            f"P(GG≥2)={result.percent}%{reliable_flag}  "
            f"Actual={'GG'+str(row['path_gg_max']) if row['path_gg_max'] not in (None,'None') else ('Benign' if row['path_benign'] in (True,'True') else '?')}  "
            f"{correct_flag}"
        )

    _write_csv(rows, csv_path)
    _print_summary(rows)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

def _print_extraction_table(rows: list[dict]) -> None:
    console.print()
    tbl = Table(box=box.SIMPLE_HEAVY, title="Extracted Patient Data")
    for col in ["patient_id", "case_type", "age", "psa", "pirads", "psad", "path_gg_max", "path_benign", "path_cribriform"]:
        tbl.add_column(col, no_wrap=True)
    for r in rows:
        excluded = r.get("excluded") in (True, "True")
        style = "dim" if excluded else ""
        tbl.add_row(
            str(r["patient_id"]),
            str(r["case_type"])[:30],
            str(r["age"] or "—"),
            str(r["psa"] or "—"),
            str(r["pirads"] or "—"),
            f"{float(r['psad']):.3f}" if r.get("psad") and r["psad"] not in (None, "None", "") else "—",
            str(r["path_gg_max"]) if r.get("path_gg_max") not in (None, "None") else ("Benign" if r.get("path_benign") in (True,"True") else "—"),
            "Yes" if r.get("path_cribriform") in (True,"True") else "No",
            "EXCL" if excluded else "",
            style=style,
        )
    console.print(tbl)


def _auc(probs: list[float], labels: list[int]) -> float:
    """Mann-Whitney AUC — no sklearn required."""
    pos = [p for p, l in zip(probs, labels) if l == 1]
    neg = [p for p, l in zip(probs, labels) if l == 0]
    if not pos or not neg:
        return float("nan")
    concordant = sum(1 for p in pos for n in neg if p > n)
    tied       = sum(1 for p in pos for n in neg if p == n)
    return (concordant + 0.5 * tied) / (len(pos) * len(neg))


def _print_summary(rows: list[dict]) -> None:
    # Only rows with a known binary outcome
    eligible = [
        r for r in rows
        if r.get("excluded") not in (True, "True")
        and r.get("path_gg2_positive") in (True, "True", False, "False")
        and r.get("predicted_prob") not in (None, "", "None")
    ]

    tp = sum(1 for r in eligible if r["predicted_gg2_pos"] in (True,"True") and r["path_gg2_positive"] in (True,"True"))
    fp = sum(1 for r in eligible if r["predicted_gg2_pos"] in (True,"True") and r["path_gg2_positive"] in (False,"False"))
    tn = sum(1 for r in eligible if r["predicted_gg2_pos"] in (False,"False") and r["path_gg2_positive"] in (False,"False"))
    fn = sum(1 for r in eligible if r["predicted_gg2_pos"] in (False,"False") and r["path_gg2_positive"] in (True,"True"))

    reliable   = [r for r in eligible if r.get("model_reliable") in (True,"True")]
    unreliable = [r for r in eligible if r.get("model_reliable") in (False,"False")]

    # AUC on all eligible rows with known outcome
    probs  = [float(r["predicted_prob"]) for r in eligible]
    labels = [1 if r["path_gg2_positive"] in (True,"True") else 0 for r in eligible]
    auc    = _auc(probs, labels)

    n_pos    = sum(labels)
    n_neg    = len(labels) - n_pos
    no_path  = sum(1 for r in rows
                   if r.get("excluded") not in (True,"True")
                   and r.get("path_gg2_positive") not in (True,"True",False,"False"))
    no_pred  = sum(1 for r in rows
                   if r.get("excluded") not in (True,"True")
                   and r.get("predicted_prob") in (None,"","None"))

    console.print("\n[bold]── Validation Summary ──[/bold]")
    console.print(f"  Total patients:           {len(rows)}")
    console.print(f"  Excluded (post-proc):     {sum(1 for r in rows if r.get('excluded') in (True,'True'))}")
    console.print(f"  Missing PI-RADS/PSA:      {no_pred}")
    console.print(f"  Missing pathology result: {no_path}")
    console.print(f"  Evaluable (known outcome + prediction): {len(eligible)}")
    console.print(f"    GG≥2 positive: {n_pos}  |  GG<2 negative: {n_neg}")
    console.print(f"  Reliable (PI-RADS 4–5):   {len(reliable)}")
    console.print(f"  Unreliable (PI-RADS ≤3):  {len(unreliable)}")
    console.print()
    console.print(f"  [bold cyan]AUC (independent validation): {auc:.3f}[/bold cyan]")
    console.print()
    console.print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    sens = tp/(tp+fn) if (tp+fn) else 0
    spec = tn/(tn+fp) if (tn+fp) else 0
    ppv  = tp/(tp+fp) if (tp+fp) else 0
    npv  = tn/(tn+fn) if (tn+fn) else 0
    console.print(f"  Sensitivity: {sens:.2f}  Specificity: {spec:.2f}")
    console.print(f"  PPV:         {ppv:.2f}  NPV:         {npv:.2f}")

    if fn > 0:
        missed = [r for r in eligible
                  if r["predicted_gg2_pos"] in (False,"False")
                  and r["path_gg2_positive"] in (True,"True")]
        console.print(f"\n  [red]False Negatives (GG≥2 missed):[/red]")
        for r in missed:
            gg = r.get("path_gg_max","?")
            console.print(f"    {r['patient_id']}  PSA={r.get('psa','?')}  PI-RADS={r.get('pirads','?')}  "
                          f"PSAD={r.get('psad','?')}  GG{gg}  P={float(r['predicted_prob']):.1%}")

    if len(reliable) > 0:
        rel_correct = sum(1 for r in reliable if r.get("correct") in (True,"True"))
        console.print(f"\n  Reliable (PI-RADS 4–5) accuracy: {rel_correct}/{len(reliable)} ({100*rel_correct//len(reliable)}%)")
    if len(unreliable) > 0:
        unrel_correct = sum(1 for r in unreliable if r.get("correct") in (True,"True"))
        console.print(f"  Unreliable (PI-RADS ≤3) accuracy: {unrel_correct}/{len(unreliable)} ({100*unrel_correct//len(unreliable)}%)")


# ─────────────────────────────────────────────────────────────────────────────
# CSV helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv(rows: list[dict], path: str) -> None:
    Path(path).parent.mkdir(exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXTRACTED_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _int(v) -> int | None:
    try: return int(v) if v not in (None, "", "None") else None
    except: return None

def _float(v) -> float | None:
    try: return float(v) if v not in (None, "", "None") else None
    except: return None

def _bool(v) -> bool | None:
    if v in (True, "True"): return True
    if v in (False, "False"): return False
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GG≥2 validation pipeline")
    sub = parser.add_subparsers(dest="cmd")

    p_extract = sub.add_parser("extract", help="Stage 1: parse documents → CSV")
    p_extract.add_argument("--dir", required=True, help="Directory or file of clinical documents")
    p_extract.add_argument("--out", default="results/extracted.csv")

    p_deident = sub.add_parser("deident", help="Stage 2: de-identify CSV with OpenMed")
    p_deident.add_argument("--in", dest="inp", default="results/extracted.csv")

    p_predict = sub.add_parser("predict", help="Stage 3: run model on CSV")
    p_predict.add_argument("--in", dest="inp", default="results/extracted.csv")

    p_all = sub.add_parser("run-all", help="Run all three stages")
    p_all.add_argument("--dir", required=True, help="Directory or file of clinical documents")
    p_all.add_argument("--out", default="results/extracted.csv")

    args = parser.parse_args()

    if args.cmd == "extract":
        stage_extract(args.dir, args.out)
    elif args.cmd == "deident":
        stage_deidentify(args.inp)
    elif args.cmd == "predict":
        stage_predict(args.inp)
    elif args.cmd == "run-all":
        stage_extract(args.dir, args.out)
        stage_deidentify(args.out)
        stage_predict(args.out)
    else:
        parser.print_help()
