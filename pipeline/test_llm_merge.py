"""
test_llm_merge.py — regression tests for LLM/regex merge priority and
disagreement logging in llm_extract.py.

Background: pipeline.py previously let regex win on every field the LLM
also tried to extract, only using the LLM to fill fields regex returned
None for. That made LLM extraction almost invisible in results, since
regex succeeds (correctly or not) on most fields most of the time. This
tests the fix: LLM now takes priority, and disagreements are logged rather
than silently dropped.

Run: python3 pipeline/test_llm_merge.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from llm_extract import merge_llm_and_regex, find_disagreements, _truncate_for_llm, _MAX_CHARS

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


print("== merge_llm_and_regex: LLM takes priority ==")

regex = {"psa": 6.2, "pirads": None, "age": None}
llm   = {"psa": 6.5, "pirads": 4,    "age": 68}
merged = merge_llm_and_regex(llm, regex)
check("LLM value wins when both sides have a value", merged["psa"] == 6.5, merged)
check("LLM fills a field regex missed", merged["pirads"] == 4, merged)
check("LLM fills a field regex missed (age)", merged["age"] == 68, merged)

print("\n== merge_llm_and_regex: regex fills LLM gaps ==")

regex2 = {"psa": 6.2, "pirads": 3}
llm2   = {"psa": None, "pirads": None}
merged2 = merge_llm_and_regex(llm2, regex2)
check("regex value used when LLM returns null", merged2["psa"] == 6.2, merged2)
check("regex value used when LLM returns null (pirads)", merged2["pirads"] == 3, merged2)

print("\n== merge_llm_and_regex: empty string treated as null ==")

merged3 = merge_llm_and_regex({"exclusion_reason": ""}, {"exclusion_reason": "prior RALP"})
check("LLM empty string doesn't override regex value", merged3["exclusion_reason"] == "prior RALP", merged3)

print("\n== find_disagreements ==")

d1 = find_disagreements({"psa": 6.5}, {"psa": 6.2})
check("flags numeric disagreement", d1 == [("psa", 6.2, 6.5)], d1)

d2 = find_disagreements({"psa": 6.2}, {"psa": 6.2})
check("no disagreement when values match", d2 == [], d2)

d3 = find_disagreements({"psa": 6.2}, {"psa": None})
check("no disagreement when only one side has a value", d3 == [], d3)

d4 = find_disagreements({"psa": 6.20000001}, {"psa": 6.2})
check("float noise within tolerance is not a disagreement", d4 == [], d4)

d5 = find_disagreements({"path_benign": True}, {"path_benign": False})
check("flags boolean disagreement", d5 == [("path_benign", False, True)], d5)

print("\n== _truncate_for_llm: pathology tail is preserved ==")

short_text = "short note"
check("short text untouched", _truncate_for_llm(short_text) == short_text)

long_note = "A" * (_MAX_CHARS + 5000)
tail_marker = "PATHOLOGY_RESULT_MARKER_GLEASON_7"
long_text = long_note + tail_marker
truncated = _truncate_for_llm(long_text)
check("truncated text stays under a sane bound", len(truncated) < len(long_text))
check("pathology-like tail content survives truncation", tail_marker in truncated, truncated[-100:])

print(f"\n{'='*50}")
if failures:
    print(f"  {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("  ALL TESTS PASSED")
sys.exit(0)
