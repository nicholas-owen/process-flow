"""Plan the next batch of preview runs from the DAGs made so far.

    python tools/adaptive.py --dims proposal.json --dags dags [--values values.json] -o next.tsv

Then, in WSL:

    bash tools/preview_matrix.sh -j 4 PIPELINE next.tsv dags -- -r REV -profile test

and repeat until the planner says there is nothing left to run.

First batch (no runs yet): the baseline (every dimension at its default) and
--initial random runs leaning towards the enabling values (flags on, paths
set), which reveal most elements quickly. Later batches: the DAGs so far are
aligned (tools/align.py), each element's runs found, and the elements whose
predicate is not yet settled get a seed run whose every one-change neighbour
is added (tools/matrix.py next_batch). On the synthetic rnaseq-flow test this
settles every element exactly, in about 230 to 270 runs over four batches;
previews run in parallel, so that is minutes per batch, not hours.

--fixed adds the same args to every run, e.g. to make the test profile
previewable (nf-core/rnaseq 3.27: --transcript_fasta '' so Kallisto can build
its index, and a dummy --sylph_db). Being the same in every run, they cannot
be mistaken for an effect of a dimension. Change them only with a fresh
--dags folder.

--values maps each path param to a real path to use when a run sets it,
e.g. {"dbgap_key": "/home/me/dummy.ngc"}. A run that unsets a param with a
default passes --param ''. Runs are named r001, r002, ... after those
already in dags/runs.tsv.
"""
import argparse, json, os, random, shlex, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from align import align
from generate import dims_from_proposal, settings_from_args
from matrix import next_batch, settled, _allowed, _key
from predicates import domain

ENABLE = {"boolean": True, "presence": "present"}


def baseline(dims):
    return settings_from_args("", list(dims.values()))


def initial(dims, n, seed=0, rich=0.7):
    rng = random.Random(seed)
    base = baseline(dims)
    runs, have = [base], {_key(base)}
    while len(runs) < n + 1:
        s = {k: (ENABLE[d["kind"]] if d["kind"] in ENABLE and rng.random() < rich else rng.choice(domain(d)))
             for k, d in dims.items()}
        if _allowed(s, dims) and _key(s) not in have:
            have.add(_key(s)); runs.append(s)
    return runs


def args_for(s, dims, base, values):
    """Command-line args that turn the baseline into settings s."""
    out, missing = [], []
    for k, d in dims.items():
        if s[k] == base[k]:
            continue
        p = d.get("param") or k
        if d["kind"] == "boolean":
            out.append(f"--{p} {'true' if s[k] else 'false'}")
        elif d["kind"] == "presence":
            # null, not '': nf-schema rejects an empty string for a path
            # (tools/preview_matrix.sh passes it through a params file)
            if s[k] == "absent":
                out.append(f"--{p} null")
            elif p in values:
                out.append(f"--{p} {shlex.quote(str(values[p]))}")
            else:
                out.append(f"--{p} <PATH>"); missing.append(p)
        elif s[k] == "unset":
            out.append(f"--{p} null")
        else:
            out.append(f"--{p} {shlex.quote(str(s[k]))}")
    return " ".join(out), missing


def read_runs(path):
    runs = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if len(cols) >= 2 and cols[1] in ("ok", "FAILED"):
                runs.append({"id": cols[0], "status": cols[1], "args": cols[2] if len(cols) > 2 else ""})
    latest = {}
    for r in runs:                           # a rerun replaces an earlier attempt
        latest[r["id"]] = r
    return list(latest.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dims", required=True, help="tools/propose.py proposal.json")
    ap.add_argument("--dags", required=True, help="the DOT folder tools/preview_matrix.sh writes")
    ap.add_argument("--values", help="JSON: path param -> a real path to use when a run sets it")
    ap.add_argument("--initial", type=int, default=10, help="random runs in the first batch (default 10)")
    ap.add_argument("--max", type=int, help="cap on runs in this batch")
    ap.add_argument("--fixed", default="", help="args added to every run, the same in all of them (e.g. to make a profile previewable)")
    ap.add_argument("--fixed-file", help="read --fixed from a file (tools/localise_testdata.py writes fixed_args.txt)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    if a.fixed_file:
        a.fixed = (open(a.fixed_file, encoding="utf-8").read().strip() + " " + a.fixed).strip()
    dims = {d["id"]: d for d in dims_from_proposal(a.dims)}
    values = json.load(open(a.values, encoding="utf-8")) if a.values else {}
    base = baseline(dims)
    done = read_runs(os.path.join(a.dags, "runs.tsv"))
    ok = [r for r in done if r["status"] == "ok" and os.path.exists(os.path.join(a.dags, r["id"] + ".dot"))]

    if not done:
        batch = initial(dims, a.initial)
        why = f"first batch: the baseline and {a.initial} random runs leaning towards enabling values"
    else:
        settings = [settings_from_args(r["args"], list(dims.values())) for r in ok]
        u = align({r["id"]: os.path.join(a.dags, r["id"] + ".dot") for r in ok})
        index = {r["id"]: i for i, r in enumerate(ok)}
        # elements are nodes and edges: an edge can exist under settings its
        # ends do not need (the samplesheet chain fed from the runinfo only
        # when downloads are skipped)
        observed = {uid: {index[x] for x in n["observed"]} for uid, n in u.nodes.items()}
        observed.update({f"edge{i}": {index[x] for x in obs} for i, obs in enumerate(u.edges.values())})
        tried = {_key(settings_from_args(r["args"], list(dims.values()))) for r in done}
        batch = [s for s in next_batch(dims, settings, observed, a.max) if _key(s) not in tried]
        unsettled = sum(1 for ix in observed.values() if ix and not settled(dims, settings, ix))
        why = (f"{len(ok)} runs so far ({len(done) - len(ok)} failed), {len(u.nodes)} nodes and {len(u.edges)} edges aligned, "
               f"{unsettled} of {len(observed)} elements not yet settled")

    n0 = max([int(r["id"][1:]) for r in done if r["id"].startswith("r") and r["id"][1:].isdigit()], default=0) + 1
    lines, missing = [], set()
    for i, s in enumerate(batch):
        args, miss = args_for(s, dims, base, values)
        missing.update(miss)
        if a.fixed:
            args = (args + " " + a.fixed).strip()
        name = "baseline" if not done and i == 0 else f"r{n0 + i - (0 if done else 1):03d}"
        lines.append(f"{name}\t{args}")
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# planned by tools/adaptive.py: {why}\n")
        f.write("".join(l + "\n" for l in lines))
    print(f"{why}.")
    if batch:
        print(f"next batch: {len(batch)} runs -> {a.out}")
    else:
        print("nothing left to run: every element seen so far is settled.")
    if missing:
        print(f"set real paths for {sorted(missing)} with --values; those runs carry <PATH> placeholders")


if __name__ == "__main__":
    main()
