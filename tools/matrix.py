"""Design a preview matrix that covers every pair of dimension values.

    from matrix import pairwise
    runs = pairwise(dims, baseline)       # list of settings dicts, baseline first

One change at a time from a baseline never shows an element that needs two
non-default settings together (rnaseq-flow's DOWNLOAD_GMT needs the DOWNLOAD
workflow and --download_gmt). A pairwise covering design puts every pair of
values of every two dimensions into at least one run, so anything that needs
at most two settings at once is seen, in not many more runs. It is the
standard way to test software with many switches cheaply.

Greedy: start from the baseline; each new run starts from the uncovered pair
seen most often, then sets every other dimension, in turn, to the value that
covers the most still-uncovered pairs. Deterministic for a given seed.

`implies` constraints are respected: a run in which an explicitly set
dimension's implication is definitely false (an aligner with the counts entry)
is never proposed, and pairs that no allowed run can contain are dropped.
"""
import itertools, random
from predicates import holds, domain


def _allowed(s, dims):
    return all(holds(d["implies"], s, dims) is not False for k, d in dims.items()
               if d.get("implies") and s.get(k) is not None)


def probes(dims, runs, observed, max_new=200):
    """Local probes around elements already seen.

    observed: element id -> set of indexes into runs where it was seen. A
    minimal set of seed runs is chosen so that every seen element is present
    in one; around each seed, every dimension is changed one value at a time.
    For an element that needs several settings at once, these are the runs
    where all of its conditions hold but one, which is what shows which
    conditions matter. Returns the new runs (implications respected, no
    duplicates of existing runs)."""
    have = {tuple(sorted((k, str(v)) for k, v in s.items())) for s in runs}
    todo = {e: set(ix) for e, ix in observed.items() if ix}
    seeds = []
    while todo:                               # greedy set cover
        counts = {}
        for ix in todo.values():
            for i in ix:
                counts[i] = counts.get(i, 0) + 1
        best = max(sorted(counts), key=lambda i: counts[i])
        seeds.append(best)
        todo = {e: ix for e, ix in todo.items() if best not in ix}
    new = []
    for i in seeds:
        for k, d in dims.items():
            for v in domain(d):
                if v == runs[i][k]:
                    continue
                s = dict(runs[i], **{k: v})
                key = tuple(sorted((kk, str(vv)) for kk, vv in s.items()))
                if key in have or not _allowed(s, dims):
                    continue
                have.add(key)
                new.append(s)
                if len(new) >= max_new:
                    return new
    return new


def pairwise(dims, baseline, seed=0, max_runs=200):
    keys = list(dims)
    dom = {k: domain(dims[k]) for k in keys}
    rng = random.Random(seed)

    def pairs_of(s):
        return {((a, s[a]), (b, s[b])) for a, b in itertools.combinations(keys, 2)}

    uncovered = {((a, va), (b, vb)) for a, b in itertools.combinations(keys, 2) for va in dom[a] for vb in dom[b]}
    runs = [dict(baseline)]
    uncovered -= pairs_of(baseline)
    # drop pairs no allowed run can hold (checked against the baseline with the pair set)
    for p in sorted(uncovered, key=str):
        s = dict(baseline, **dict(p))
        if not _allowed(s, dims):
            # try to make it allowed by changing other dimensions
            ok = False
            for _ in range(50):
                t = dict(s)
                for k in keys:
                    if k not in dict(p) and rng.random() < 0.5:
                        t[k] = rng.choice(dom[k])
                if _allowed(t, dims):
                    ok = True
                    break
            if not ok:
                uncovered.discard(p)
    while uncovered and len(runs) < max_runs:
        (a, va), (b, vb) = sorted(uncovered, key=lambda p: (p[0][0], str(p[0][1]), p[1][0], str(p[1][1])))[0]
        s = dict(baseline, **{a: va, b: vb})
        for k in rng.sample(keys, len(keys)):
            if k in (a, b):
                continue
            best, gain = s[k], -1
            for v in dom[k]:
                t = dict(s, **{k: v})
                g = len(pairs_of(t) & uncovered)
                if g > gain or (g == gain and v == baseline[k]):
                    best, gain = v, g
            s[k] = best
        if not _allowed(s, dims):
            # fall back to the baseline elsewhere; if still not allowed, give the pair up
            s = dict(baseline, **{a: va, b: vb})
            if not _allowed(s, dims):
                uncovered.discard(((a, va), (b, vb)))
                continue
        new = pairs_of(s) & uncovered
        if not new:
            uncovered.discard(((a, va), (b, vb)))
            continue
        runs.append(s)
        uncovered -= new
    return runs


# ---- adaptive design: probe only what is not settled ----------------------------
def _key(s):
    return tuple(sorted((k, str(v)) for k, v in s.items()))


def neighbours(dims, s):
    """Every allowed run that differs from s in exactly one dimension."""
    out = []
    for k, d in dims.items():
        for v in domain(d):
            if v != s[k]:
                t = dict(s, **{k: v})
                if _allowed(t, dims):
                    out.append(t)
    return out


def local_conjunction(dims, seed, present):
    """What a fully probed seed shows about one element: for each dimension,
    the values at which the element is still present when only that
    dimension changes. Dimensions where every value keeps it are dropped.
    present(settings) -> bool, for runs already made."""
    conds = {}
    for k, d in dims.items():
        # A value the pipeline forbids at this seed (an `implies` that fails)
        # was never run, so it says nothing about the element: it is kept,
        # not counted as the element disappearing. Counting it taught
        # nf-core/rnaseq's Kallisto index edge a false "input is not unmapped".
        ok = [v for v in domain(d) if v == seed[k] or not _allowed(dict(seed, **{k: v}), dims)
              or present(dict(seed, **{k: v}))]
        if len(ok) < len(domain(d)):
            if d["kind"] == "boolean":
                conds[k] = ok[0] if len(ok) == 1 else None
            elif d["kind"] == "presence":
                conds[k] = {"present": ok[0] not in (False, "absent")} if len(ok) == 1 else None
            else:
                conds[k] = ok if len(ok) > 1 else ok[0]
            if conds[k] is None:
                del conds[k]
    return {"params": conds}


def settled(dims, runs, element_runs):
    """Is an element settled? Every run it appears in must be explained by a
    fully probed seed: either it is one, or it satisfies the local conjunction
    a fully probed seed taught (another branch of an `any` needs its own seed).
    element_runs: indexes into runs where the element appears."""
    have = {_key(s): i for i, s in enumerate(runs)}
    pos = {_key(runs[i]) for i in element_runs}
    present = lambda s: _key(s) in pos
    seeds = [runs[i] for i in element_runs
             if all(_key(t) in have for t in neighbours(dims, runs[i]))]
    if not seeds:
        return False
    learnt = [local_conjunction(dims, s, present) for s in seeds]
    return all(any(holds(c, runs[i], dims) is True for c in learnt) for i in element_runs)


def next_batch(dims, runs, observed, max_new=None):
    """The next runs to make: neighbours of seeds chosen so that every
    unsettled element seen so far gets a fully probed seed.

    runs: settings so far; observed: element id -> set of run indexes where
    it was seen. Seeds are taken greedily, each the run (among those an
    unsettled element appears in, and not yet fully probed) that the most
    unsettled elements appear in, preferring seeds whose neighbours are
    mostly made already. An element whose runs are all explained after its
    seed is probed is not given a second seed in the same batch; any branch
    of an `any` that remains is found in the next batch."""
    have = {_key(s) for s in runs}
    unsettled = {e: ix for e, ix in observed.items() if ix and not settled(dims, runs, ix)}
    planned, batch = set(), []
    while unsettled:
        score = {}
        for e, ix in unsettled.items():
            for i in ix:
                if _key(runs[i]) in planned:
                    continue
                missing = [t for t in neighbours(dims, runs[i]) if _key(t) not in have]
                if not missing:
                    continue            # already fully probed: its element is unsettled for another branch
                score.setdefault(i, [0, len(missing)])[0] += 1
        if not score:
            break
        best = max(sorted(score), key=lambda i: (score[i][0], -score[i][1]))
        planned.add(_key(runs[best]))
        for t in neighbours(dims, runs[best]):
            if _key(t) not in have:
                have.add(_key(t))
                batch.append(t)
        unsettled = {e: ix for e, ix in unsettled.items() if best not in ix}
        if max_new and len(batch) >= max_new:
            break
    return batch
