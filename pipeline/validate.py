"""
validate.py — Interactive CLI for validating the GG≥2 model against real biopsy cases.

Usage:
  python validate.py                    # interactive mode: paste note, get prediction, enter outcome
  python validate.py --file cases/      # batch mode: process all .txt files in cases/
  python validate.py --summary          # print summary of results/results.csv

Each case:
  1. Paste (or load) clinical note
  2. Model predicts P(GG≥2)
  3. You enter actual pathology outcome
  4. Row appended to results/results.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box

from extract import extract_fields, extract_pathology, read_file, split_patients, split_note_pathology
from model import predict

console = Console()
RESULTS_CSV = Path("results/results.csv")
CSV_HEADERS = [
    "case_id", "age", "psa", "pirads", "psad", "prostate_volume_cc",
    "predicted_prob", "predicted_gg2_pos", "model_reliable",
    "actual_gg_max", "actual_gg2_pos", "benign", "cribriform",
    "correct", "notes",
]


def _read_csv() -> list[dict]:
    if not RESULTS_CSV.exists():
        return []
    with open(RESULTS_CSV) as f:
        return list(csv.DictReader(f))


def _append_row(row: dict) -> None:
    RESULTS_CSV.parent.mkdir(exist_ok=True)
    write_header = not RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def run_case(note_text: str, path_text: str, case_id: str) -> dict:
    """Extract → predict → compare → return row dict."""
    cf = extract_fields(note_text, case_id=case_id)

    if cf.excluded:
        console.rule(f"[bold]Case {case_id}[/bold]")
        console.print(f"  [yellow]EXCLUDED — {cf.exclusion_reason}[/yellow]\n")
        return {k: None for k in CSV_HEADERS} | {"case_id": case_id, "notes": cf.exclusion_reason}

    path = extract_pathology(path_text)
    result = predict(cf.pirads, cf.psa, cf.psad) if cf.pirads and cf.psa else None

    predicted_prob = round(result.prob, 4) if result else None
    predicted_gg2_pos = (result.prob >= 0.5) if result else None
    actual_gg2_pos = path["gg2_positive"] if path["gg_max"] is not None else (False if path["benign"] else None)
    correct = (predicted_gg2_pos == actual_gg2_pos) if (predicted_gg2_pos is not None and actual_gg2_pos is not None) else None

    # Print summary
    console.rule(f"[bold]Case {case_id}[/bold]")
    tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    tbl.add_column("Field", style="dim")
    tbl.add_column("Value", style="bold")
    tbl.add_row("Age", str(cf.age or "—"))
    tbl.add_row("PSA", f"{cf.psa} ng/mL" if cf.psa else "—")
    tbl.add_row("PI-RADS", str(cf.pirads or "—"))
    tbl.add_row("PSAD", f"{cf.psad:.3f} ng/mL²" if cf.psad else "—")
    tbl.add_row("Volume", f"{cf.prostate_volume_cc} cc" if cf.prostate_volume_cc else "—")
    console.print(tbl)

    if result:
        reliability = "" if result.reliable else " [yellow](⚠ model unreliable at PI-RADS ≤3)[/yellow]"
        console.print(f"  Predicted P(GG≥2): [bold cyan]{result.percent}%[/bold cyan]{reliability}")
        console.print(f"  AUA 2026 rate:     {result.guideline_rate}")
        if result.psad_tier:
            console.print(f"  PSAD tier:         {result.psad_tier}")
    else:
        console.print("  [red]Could not run model — PSA or PI-RADS missing[/red]")

    gg_label = f"GG{path['gg_max']}" if path["gg_max"] else ("Benign" if path["benign"] else "Unknown")
    gg2_label = "[green]GG≥2 YES[/green]" if actual_gg2_pos else "[dim]GG≥2 NO[/dim]"
    console.print(f"  Actual outcome:    [bold]{gg_label}[/bold]  {gg2_label}")
    if path["cribriform"]:
        console.print("  [yellow]Cribriform present[/yellow]")

    if correct is True:
        verdict = "[green]✓ CORRECT[/green]"
    elif correct is False:
        verdict = "[red]✗ WRONG[/red]"
    else:
        verdict = "[dim]— unknown[/dim]"
    console.print(f"  Model verdict:     {verdict}\n")

    return {
        "case_id": case_id,
        "age": cf.age,
        "psa": cf.psa,
        "pirads": cf.pirads,
        "psad": cf.psad,
        "prostate_volume_cc": cf.prostate_volume_cc,
        "predicted_prob": predicted_prob,
        "predicted_gg2_pos": predicted_gg2_pos,
        "model_reliable": result.reliable if result else None,
        "actual_gg_max": path["gg_max"],
        "actual_gg2_pos": actual_gg2_pos,
        "benign": path["benign"],
        "cribriform": path["cribriform"],
        "correct": correct,
        "notes": "; ".join(cf.extraction_notes),
    }


def print_summary() -> None:
    rows = _read_csv()
    if not rows:
        console.print("[dim]No results yet.[/dim]")
        return

    total = len(rows)
    reliable = [r for r in rows if r["model_reliable"] == "True"]
    unreliable = [r for r in rows if r["model_reliable"] != "True"]

    def accuracy(subset):
        known = [r for r in subset if r["correct"] in ("True", "False")]
        if not known:
            return None
        correct = sum(1 for r in known if r["correct"] == "True")
        return correct, len(known)

    console.rule("[bold]Validation Summary[/bold]")

    tbl = Table(box=box.SIMPLE_HEAVY)
    tbl.add_column("Case", style="dim")
    tbl.add_column("Age")
    tbl.add_column("PSA")
    tbl.add_column("PI-RADS")
    tbl.add_column("PSAD")
    tbl.add_column("Predicted %")
    tbl.add_column("Reliable")
    tbl.add_column("Actual GG")
    tbl.add_column("GG≥2")
    tbl.add_column("Correct")

    for r in rows:
        correct_str = "[green]✓[/green]" if r["correct"] == "True" else ("[red]✗[/red]" if r["correct"] == "False" else "—")
        reliable_str = "✓" if r["model_reliable"] == "True" else "[yellow]⚠[/yellow]"
        gg_str = f"GG{r['actual_gg_max']}" if r["actual_gg_max"] and r["actual_gg_max"] != "None" else ("Benign" if r["benign"] == "True" else "—")
        tbl.add_row(
            r["case_id"],
            r["age"] or "—",
            r["psa"] or "—",
            r["pirads"] or "—",
            f"{float(r['psad']):.3f}" if r["psad"] and r["psad"] != "None" else "—",
            f"{float(r['predicted_prob'])*100:.1f}%" if r["predicted_prob"] and r["predicted_prob"] != "None" else "—",
            reliable_str,
            gg_str,
            "[green]Yes[/green]" if r["actual_gg2_pos"] == "True" else "[dim]No[/dim]",
            correct_str,
        )
    console.print(tbl)

    console.print(f"\n  Total cases: {total}")
    all_acc = accuracy(rows)
    if all_acc:
        console.print(f"  Overall accuracy: {all_acc[0]}/{all_acc[1]} ({100*all_acc[0]//all_acc[1]}%)")
    rel_acc = accuracy(reliable)
    if rel_acc:
        console.print(f"  Reliable (PI-RADS 4–5) accuracy: {rel_acc[0]}/{rel_acc[1]} ({100*rel_acc[0]//rel_acc[1]}%)")
    unrel_acc = accuracy(unreliable)
    if unrel_acc:
        console.print(f"  Unreliable (PI-RADS ≤3) accuracy: {unrel_acc[0]}/{unrel_acc[1]} ({100*unrel_acc[0]//unrel_acc[1]}%)")

    tp = sum(1 for r in rows if r["predicted_gg2_pos"] == "True" and r["actual_gg2_pos"] == "True")
    fp = sum(1 for r in rows if r["predicted_gg2_pos"] == "True" and r["actual_gg2_pos"] == "False")
    tn = sum(1 for r in rows if r["predicted_gg2_pos"] == "False" and r["actual_gg2_pos"] == "False")
    fn = sum(1 for r in rows if r["predicted_gg2_pos"] == "False" and r["actual_gg2_pos"] == "True")
    console.print(f"\n  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    if tp + fp > 0:
        console.print(f"  Precision: {tp/(tp+fp):.2f}   Sensitivity: {tp/(tp+fn):.2f}" if (tp+fn) > 0 else "")


def interactive_mode() -> None:
    console.print("[bold]GG≥2 Model Validator[/bold] — paste clinical note, then pathology result.\n")
    case_num = len(_read_csv()) + 1

    while True:
        console.print(f"[bold cyan]Case {case_num}[/bold cyan] — paste clinical note (blank line + END to finish, or 'q' to quit):")
        lines = []
        while True:
            line = input()
            if line.strip().lower() == "q":
                print_summary()
                return
            if line.strip() == "END":
                break
            lines.append(line)
        note = "\n".join(lines).strip()
        if not note:
            continue

        console.print("Paste pathology result (blank line + END to finish):")
        path_lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            path_lines.append(line)
        path_text = "\n".join(path_lines).strip()

        case_id = f"case_{case_num:03d}"
        row = run_case(note, path_text, case_id)
        _append_row(row)
        case_num += 1


def batch_mode(cases_dir: str) -> None:
    cases_path = Path(cases_dir)
    SUPPORTED = {".txt", ".pdf", ".docx", ".doc"}

    if cases_path.is_file():
        all_files = [cases_path]
    else:
        all_files = sorted(
            f for f in cases_path.iterdir()
            if f.suffix.lower() in SUPPORTED and ".path." not in f.name
        )
    console.print(f"[bold]Found {len(all_files)} document(s) in {cases_dir}[/bold]\n")

    for doc_file in all_files:
        case_id = doc_file.stem

        try:
            full_text = read_file(doc_file)
        except Exception as e:
            console.print(f"[red]Could not read {doc_file.name}: {e}[/red]")
            continue

        # Try sidecar pathology file first (case_XXX.path.txt / .pdf / .docx)
        sidecar = next(
            (cases_path / f"{case_id}.path{s}"
             for s in [".txt", ".pdf", ".docx"]
             if (cases_path / f"{case_id}.path{s}").exists()),
            None,
        )
        if sidecar:
            try:
                note_text = full_text
                path_text = read_file(sidecar)
                console.print(f"[dim]{doc_file.name} + sidecar {sidecar.name}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not read sidecar: {e}[/yellow]")
                note_text, path_text = split_note_pathology(full_text)
        else:
            # Auto-split: clinical note at top, pathology section further down
            note_text, path_text = split_note_pathology(full_text)
            if path_text:
                console.print(f"[dim]{doc_file.name} — auto-split into note + pathology[/dim]")
            else:
                console.print(f"[dim]{doc_file.name} — no pathology section found[/dim]")

        # Split document into individual patient sections
        patient_sections = split_patients(full_text)
        console.print(f"[dim]  → {len(patient_sections)} patient section(s) found[/dim]")

        for i, section in enumerate(patient_sections, 1):
            patient_id = f"{case_id}_p{i:02d}" if len(patient_sections) > 1 else case_id
            note_text, path_text = split_note_pathology(section)
            if not path_text:
                console.print(f"[yellow]  {patient_id}: no pathology section found — skipping outcome[/yellow]")
            row = run_case(note_text, path_text, patient_id)
            _append_row(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GG≥2 model validator")
    parser.add_argument("--file", "--dir", dest="file", metavar="DIR", help="Batch mode: directory of clinical documents (PDF/DOCX/TXT)")
    parser.add_argument("--summary", action="store_true", help="Print summary of results/results.csv")
    args = parser.parse_args()

    if args.summary:
        print_summary()
    elif args.file:
        batch_mode(args.file)
    else:
        interactive_mode()
