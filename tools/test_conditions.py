"""Conditions read from source (tools/conditions.py) against the Analyser
models: every process's `when` over every allowed setting.

    python tools/test_conditions.py

Expected: nf-core/fetchngs 1.13.0 9 of 9 exact; nf-core/rnaseq 3.27.0 94 of
101 exact, 7 unknown (the RSeQC modules, chosen in a helper function that
mutates a list and reads the GTF), none wrong.

Then every node and edge (tools/graph_conditions.py): fetchngs 117 of 117
exact; nf-core/rnaseq at least 1,902 of 2,289 exact and at most 281 wrong
(a floor, so an improvement passes and a regression fails).
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES = [
    ("nf-core/fetchngs 1.13.0", "working_docs/fetchngs-src", "examples/published/nf-core-fetchngs-1.13.0.json", {"exact": 9}),
    ("nf-core/rnaseq 3.27.0", "working_docs/rnaseq-src", "examples/published/nf-core-rnaseq-3.27.0.json", {"exact": 94, "unknown": 7}),
]


def main():
    failed = False
    for name, src, model, want in CASES:
        src, model = os.path.join(ROOT, src), os.path.join(ROOT, model)
        if not (os.path.exists(src) and os.path.exists(model)):
            print(f"{name}: skipped (no source or model)"); continue
        with tempfile.TemporaryDirectory() as d:
            rep = os.path.join(d, "r.json")
            subprocess.run([sys.executable, os.path.join(HERE, "conditions.py"), "--source", src, "--model", model,
                            "--profile-config", os.path.join(src, "conf", "test.config"), "--report", rep],
                           check=True, capture_output=True)
            got = {k: v for k, v in json.load(open(rep, encoding="utf-8"))["tally"].items() if v}
        ok = got == want
        failed |= not ok
        print(f"{name}: {'ok' if ok else 'FAILED'} {got}" + ("" if ok else f" (expected {want})"))
    GRAPH = [("nf-core/fetchngs 1.13.0", CASES[0][1], CASES[0][2], 117, 0),
             ("nf-core/rnaseq 3.27.0", CASES[1][1], CASES[1][2], 1902, 281)]
    for name, src, model, min_exact, max_wrong in GRAPH:
        src, model = os.path.join(ROOT, src), os.path.join(ROOT, model)
        if not (os.path.exists(src) and os.path.exists(model)):
            print(f"{name} graph: skipped"); continue
        with tempfile.TemporaryDirectory() as d:
            rep = os.path.join(d, "r.json")
            subprocess.run([sys.executable, os.path.join(HERE, "graph_conditions.py"), "--source", src, "--model", model,
                            "--profile-config", os.path.join(src, "conf", "test.config"), "--report", rep],
                           check=True, capture_output=True)
            tally = json.load(open(rep, encoding="utf-8"))["tally"]
        exact = sum(c.get("exact", 0) for c in tally.values())
        wrong = sum(c.get("wrong", 0) for c in tally.values())
        total = sum(sum(c.values()) for c in tally.values())
        ok = exact >= min_exact and wrong <= max_wrong
        failed |= not ok
        print(f"{name} graph: {'ok' if ok else 'FAILED'} {exact} of {total} exact, {wrong} wrong"
              + ("" if ok else f" (expected at least {min_exact} exact, at most {max_wrong} wrong)"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
