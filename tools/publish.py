"""Turn a full channel model into the published form a pipeline ships.

    python tools/publish.py out/adaptive-rnaseq3/rnaseq.json \\
        --dims out/propose-rnaseq/proposal-enums.json -o channels.json

A pipeline's author runs the Analyser (the preview matrix) once per release
and commits the published model to the pipeline's repo, e.g. at
assets/process-flow/channels.json. The Explorer loads it for exact
conditions on every route and overlays a user's own run.

What changes from the full model:

  - per-run evidence goes: every element's `observed_in` list and the
    `runs` table (with the author's local paths). For nf-core/rnaseq that is
    most of the size.
  - a version stamp: repository, revision, release and Nextflow version
    (from the model, else from the runs' Nextflow logs), the process-flow
    version, and `form: published`. A model is only valid for the revision
    it was built from.
  - `generated.evidence`, a summary of how the model was proven: runs that
    worked and failed (with the settings and error of each failure), the
    args fixed in every run (paths reduced to file names), dimensions shown
    to change nothing, dimensions never varied alone, params that are tested
    in the code but were not varied (the model is exact only with them at the
    test profile's values), elements whose `when` the matrix did not settle
    (also marked `settled: false`), and disagreements between each `when`
    and the runs (should be 0).

--revision, --repository and --version fill or correct the stamp when the
runs' Nextflow logs are not beside the DOT files.

--dims is the proposal the matrix was planned from; without it the
unsettled elements and unvaried params cannot be worked out and are left out.
"""
import argparse, collections, json, os, re, shlex, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from generate import dims_from_proposal, stamp_from_logs, resolve
from matrix import settled
from predicates import holds
from version import VERSION

NOT_VARIED_SKIP = re.compile(r"^(hidden|required|standard nf-core group|output, resource)")


def _short(arg):
    """A fixed arg's value as it means something to someone else: a path is
    reduced to its file name."""
    return os.path.basename(arg) if "/" in arg or "\\" in arg else arg


def fixed_args(runs):
    """The args every run shares, in order, as (param, value) pairs."""
    lists = []
    for r in runs:
        toks, pairs = shlex.split(r.get("args", "")), []
        for i, t in enumerate(toks):
            if t.startswith("--"):
                v = toks[i + 1] if i + 1 < len(toks) and not toks[i + 1].startswith("--") else ""
                pairs.append((t[2:], v))
        lists.append(pairs)
    if not lists:
        return []
    common = set(lists[0]).intersection(*map(set, lists[1:]))
    return [p for p in lists[0] if p in common]


def failure(run, base_dir):
    """The last line of a failed run's Nextflow log: its error."""
    try:
        log = os.path.splitext(resolve(run["dag"], base_dir))[0] + ".log"
    except (FileNotFoundError, KeyError):
        return run.get("error")
    if not os.path.exists(log):
        return run.get("error")
    lines = [l.strip() for l in open(log, encoding="utf-8", errors="replace") if l.strip()]
    return lines[-1] if lines else None


def publish(model, proposal=None, base_dir=".", stamp_over=None):
    runs = model.get("runs", [])
    ok = [r for r in runs if r["status"] == "ok"]
    bad = [r for r in runs if r["status"] != "ok"]
    dims = {d["id"]: d for d in model["dimensions"]}
    index = {r["id"]: i for i, r in enumerate(ok)}
    elements = model["nodes"] + model["edges"]

    # every `when` against every run it was built from
    disagree, cache = 0, {}
    for x in elements:
        if "observed_in" not in x:
            continue
        seen = set(x["observed_in"])
        key = json.dumps(x.get("when"), sort_keys=True)
        if key not in cache:
            cache[key] = {r["id"] for r in ok if holds(x.get("when"), r["settings"], dims) is True}
        disagree += len(cache[key] ^ seen)

    # elements the matrix did not settle, judged as the planner judges them
    unsettled, not_varied, fixed_dims = [], [], []
    if proposal:
        pdims = {d["id"]: d for d in dims_from_proposal(proposal)}
        # a dimension no run varied was held fixed: it is a param not varied,
        # not a reason for every element to count as unsettled
        fixed_dims = [k for k in pdims if len({json.dumps(r["settings"].get(k)) for r in ok}) < 2]
        not_varied += fixed_dims
        pdims = {k: d for k, d in pdims.items() if k not in fixed_dims}
        settings = [{k: r["settings"].get(k) for k in pdims} for r in ok]
        memo = {}
        for x in elements:
            ix = frozenset(index[i] for i in x.get("observed_in", []) if i in index)
            if not ix:
                continue
            if ix not in memo:
                memo[ix] = settled(pdims, settings, ix)
            if not memo[ix]:
                unsettled.append(x["id"])
        for p in json.load(open(proposal, encoding="utf-8"))["params"]:
            if not p.get("include") and p.get("tested_in") and not NOT_VARIED_SKIP.match(p.get("reason", ""))                     and p["param"] not in not_varied:
                not_varied.append(p["param"])

    stamp = dict(model["pipeline"])
    stamp.update({k: v for k, v in (stamp_over or {}).items() if v})
    if stamp.get("revision", "unrecorded") == "unrecorded" or not stamp.get("nextflow_version"):
        logged = stamp_from_logs(ok, base_dir)
        for k in ("revision", "repository", "version", "nextflow_version"):
            if logged.get(k) and (not stamp.get(k) or stamp.get(k) == "unrecorded"):
                stamp[k] = logged[k]

    used = set()
    def walk(p):
        if p:
            used.update(p.get("params", {})); [walk(a) for a in p.get("any", [])]; walk(p.get("not"))
    for x in elements:
        walk(x.get("when")); walk(x.get("flows_when"))
    never_alone = [d for d in dims if d not in used and d not in fixed_dims and d != model.get("routes", {}).get("dimension")]
    dropped = sorted(set(proposal and [d["id"] for d in dims_from_proposal(proposal)] or []) - set(dims))

    evidence = {
        "design": "adaptive preview matrix (nextflow run -preview -with-dag)",
        "runs_ok": len(ok),
        "runs_failed": len(bad),
        "failed": [{"settings": r.get("settings", {}), "error": failure(r, base_dir)} for r in bad],
        "fixed_args": [{"param": p, "value": _short(v)} for p, v in fixed_args(runs)],
        "dimensions_dropped": dropped,
        "dimensions_never_varied_alone": never_alone,
        "params_not_varied": not_varied,
        "unsettled": sorted(unsettled),
        "disagreements": disagree,
    }
    if not proposal:
        for k in ("dimensions_dropped", "params_not_varied", "unsettled"):
            evidence.pop(k)

    unsettled = set(unsettled)
    def slim(x):
        y = {k: v for k, v in x.items() if k != "observed_in"}
        if x["id"] in unsettled:
            y["settled"] = False
        return y

    gen = dict(model.get("generated", {}))
    gen.pop("sources", None)
    gen["tool"] = (gen.get("tool", "") + "; published by process-flow tools/publish.py").lstrip("; ")
    gen["process_flow_version"] = VERSION
    gen["evidence"] = evidence
    out = {"schema_version": model["schema_version"], "form": "published", "pipeline": stamp, "generated": gen}
    for k in ("dimensions", "routes", "palette", "lanes", "groups"):
        if k in model:
            out[k] = model[k]
    # a filter for a dimension no run varied would promise what nothing showed
    out["dimensions"] = [d for d in model["dimensions"] if d["id"] in used or d["id"] not in fixed_dims]
    out["nodes"] = [slim(n) for n in model["nodes"]]
    out["edges"] = [slim(e) for e in model["edges"]]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", help="a full model from tools/generate.py")
    ap.add_argument("--dims", help="the proposal.json the matrix was planned from")
    ap.add_argument("--revision"); ap.add_argument("--repository"); ap.add_argument("--version")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    model = json.load(open(a.model, encoding="utf-8"))
    if model.get("form") == "published":
        ap.error(f"{a.model} is already published")
    out = publish(model, a.dims, os.path.dirname(os.path.abspath(a.model)),
                  {"revision": a.revision, "repository": a.repository, "version": a.version})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    ev, p = out["generated"]["evidence"], out["pipeline"]
    print(f"wrote {a.out}: {os.path.getsize(a.out) / 1e6:.2f} MB (from {os.path.getsize(a.model) / 1e6:.2f} MB)")
    print(f"  {p['name']} {p.get('version', '?')} at {p.get('revision')}, Nextflow {p.get('nextflow_version', '?')}, "
          f"process-flow {VERSION}")
    print(f"  {ev['runs_ok']} runs ok, {ev['runs_failed']} failed; {ev['disagreements']} disagreements; "
          f"{len(ev.get('unsettled', []))} unsettled; fixed args: {', '.join(f['param'] for f in ev['fixed_args']) or '-'}")
    if ev.get("params_not_varied"):
        print(f"  tested in the code but not varied ({len(ev['params_not_varied'])}): {', '.join(ev['params_not_varied'])}")


if __name__ == "__main__":
    main()
