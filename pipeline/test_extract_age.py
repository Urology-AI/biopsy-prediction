"""
test_extract_age.py — regression tests for age de-identification/extraction.

OpenMed's de-identification previously masked every AGE-tagged entity
unconditionally, which meant `extract_fields()`'s age regex almost never
found anything (coverage was ~4% across the real dataset). These tests
cover the fix: ages under MAX_SAFE_AGE are restored after de-identification
so they remain usable, while everything else (name, phone, older ages)
stays masked, and older/high-risk ages still don't leak.

Run: python3 pipeline/test_extract_age.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "model"))
sys.path.insert(0, str(Path(__file__).parent))
from extract import deidentify_note, extract_fields, MAX_SAFE_AGE

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== Age restoration (below MAX_SAFE_AGE) ==")

deid = deidentify_note("John Smith, 68 year old male with PSA 6.2, seen for consult.")
check("safe age (68) restored in de-identified text", "68" in deid, deid)
check("name still masked", "John" not in deid and "Smith" not in deid, deid)
check("no residual [age] placeholder when restored", "[age]" not in deid, deid)

cf = extract_fields(deid, already_deidentified=True)
check("extract_fields picks up restored age from mid-note text", cf.age == 68, cf.age)

print(f"\n== Ages at/above MAX_SAFE_AGE ({MAX_SAFE_AGE}) stay masked ==")

deid_old = deidentify_note("Jane Doe, 91 year old female with PSA 8.1, contact 555-1234.")
check("high age (91) NOT present in text", "91" not in deid_old, deid_old)
check("high age left as [age] placeholder", "[age]" in deid_old, deid_old)
check("name still masked for high-age case too", "Jane" not in deid_old and "Doe" not in deid_old, deid_old)

cf_old = extract_fields(deid_old, already_deidentified=True)
check("extract_fields does not recover a masked high age", cf_old.age is None, cf_old.age)

print("\n== Age extraction patterns (top-of-note vs mid-note) ==")

top_of_note = "72\nType: AR, MRI guided KOELIS\nPSA 4.47"
cf_top = extract_fields(top_of_note, already_deidentified=True)
check("top-of-note bare-number age still works (pre-existing behavior)", cf_top.age == 72, cf_top.age)

mid_note = "Pt is a 55 year old male referred for MRI guided TP prostate biopsy. PSA 5.0"
cf_mid = extract_fields(mid_note, already_deidentified=True)
check("mid-note 'NN year old' age pattern works", cf_mid.age == 55, cf_mid.age)

mid_note_yo = "Pt 60yo male, PSA 4.0, referred for biopsy"
cf_yo = extract_fields(mid_note_yo, already_deidentified=True)
check("mid-note 'NNyo' age pattern works", cf_yo.age == 60, cf_yo.age)

age_colon = "History reviewed. age: 58. PSA 3.2"
cf_colon = extract_fields(age_colon, already_deidentified=True)
check("'age: NN' pattern works", cf_colon.age == 58, cf_colon.age)

print(f"\n{'='*50}")
if failures:
    print(f"  {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")
sys.exit(0)
