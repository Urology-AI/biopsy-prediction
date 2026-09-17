"""
test_cross_impl.py — asserts model.py (this repo, the training/validation
source of truth) and @urology-ai/epsa-engine's predictBiopsyRisk (the JS/TS
port consumed by e-psa/backend, Urology-AI/epsa-engine's src/biopsyRisk.js)
agree bit-for-bit on the same inputs.

This is the test that would have caught a v4-coefficient transcription typo
before it reached patients — previously nothing asserted the two
implementations matched at all; e-psa/backend just hand-copied coefficients
into biopsyPrediction.ts and hoped they stayed in sync (see
Urology-AI/e-psa-calculator#202, which replaced that hand-copy with a real
call into the engine — this test is what backs that change up going
forward).

Requires `npm install` to have been run in this directory (tests/package.json)
against a registry with read access to @urology-ai/epsa-engine.

Run: python3 tests/test_cross_impl.py
"""

import json
import math
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR.parent / "model"))
from model import predict  # noqa: E402

CHECK_SCRIPT = TESTS_DIR / "cross_impl_check.mjs"

CASES = [
    # v4 path (volume provided)
    {"pirads": 4, "psa": 6.0, "prostate_volume_cc": 40.0},
    {"pirads": 1, "psa": 3.2, "prostate_volume_cc": 55.0},
    {"pirads": 5, "psa": 22.4, "prostate_volume_cc": 28.0},
    {"pirads": 3, "psa": 9.9, "prostate_volume_cc": 61.5},
    # v3 fallback (psad, no volume)
    {"pirads": 4, "psa": 6.0, "psad": 0.15},
    {"pirads": 2, "psa": 4.1, "psad": 0.08},
    # v2 fallback (neither)
    {"pirads": 4, "psa": 6.0},
    {"pirads": 5, "psa": 12.0},
]

failures = []


def run_js(case):
    proc = subprocess.run(
        ["node", str(CHECK_SCRIPT), json.dumps(case)],
        cwd=TESTS_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


for case in CASES:
    py_result = predict(
        pirads=case["pirads"],
        psa=case["psa"],
        psad=case.get("psad"),
        prostate_volume_cc=case.get("prostate_volume_cc"),
    )
    js_result = run_js(case)

    name = f"pirads={case['pirads']} psa={case['psa']} vol={case.get('prostate_volume_cc')} psad={case.get('psad')}"

    check(
        f"{name}: prob matches",
        math.isclose(py_result.prob, js_result["prob"], rel_tol=1e-9),
        f"py={py_result.prob} js={js_result['prob']}",
    )
    check(
        f"{name}: reliable flag matches",
        py_result.reliable == js_result["reliable"],
    )
    check(
        f"{name}: guideline_rate matches",
        py_result.guideline_rate == js_result["guidelineRate"],
    )
    if py_result.psad is not None:
        check(
            f"{name}: psad_tier matches",
            (py_result.psad_tier or "") in (js_result["psadTier"] or ""),
            f"py={py_result.psad_tier} js={js_result['psadTier']}",
        )

print(f"\n{'='*50}")
if failures:
    print(f"  {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("  ALL CROSS-IMPLEMENTATION CHECKS PASSED")
sys.exit(0)
