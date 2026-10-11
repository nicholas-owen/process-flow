"""Infer `when` predicates from where elements were observed.

    from infer import infer
    pred, ok = infer(observed_runs, settings_by_run, dims)

Given the runs an element appeared in, each run's settings (dimension id ->
value; None where a dimension does not apply to that run) and the dimension
records, find the simplest predicate that holds in exactly those runs:

  1. Observed in every run: no predicate.
  2. One conjunction: for each dimension, the values seen in the positive runs
     give a condition; choose the fewest conditions that rule out every
     negative run (exhaustively over small subsets, so the choice is minimal,
     preferring dimensions that apply to every positive run).
  3. Otherwise an `any` of conjunctions: take an uncovered positive run, fix
     every dimension to its value there, drop conditions while no negative run
     becomes covered, widen each remaining condition to every value that keeps
     it so; repeat until every positive is covered. Then merge alternatives
     that differ in one dimension, and lift conditions shared by all of them.

Conditions are written in the schema's forms: a scalar or a list for enums, a
boolean, {"present": ...} for presence, {"min": ...} for an ordinal whose
values form an upper range.

The result is checked against every run with tools/predicates.py; ok is False
when no predicate over these dimensions can fit, i.e. two runs with the same
settings disagree. That means a dimension is missing, and is reported.

A predicate fitted to a handful of runs is a hypothesis about the others. It
agrees with every run it was fitted to; how it generalises depends on how well
the matrix covers the dimensions (Phase 2, step 3).
"""
import itertools, random
from predicates import holds


def _equivalent(p, q, dims):
    """Do two predicates agree on every combination of the dimensions they mention?"""
    from predicates import variables, domain
    ds = sorted(variables(p) | variables(q))
    for combo in itertools.product(*(domain(dims[d]) for d in ds)):
        s = dict(zip(ds, combo))
        if (holds(p, s, dims) is True) != (holds(q, s, dims) is True):
            return False
    return True


def _size(c):
    return len(c) if isinstance(c, list) else 1


def _excludes(conds, neg, settings, dims):
    """True when the conjunction is definitely false on every negative run."""
    return all(holds({"params": conds}, settings[r], dims) is False for r in neg)


def _covered(conds, runs, settings, dims):
    return sum(holds({"params": conds}, settings[r], dims) is True for r in runs)


def _specific(runs, settings, dims):
    """The most specific conjunction true on every run in `runs`: each
    dimension that applies to all of them, restricted to the values seen."""
    conds = {}
    for d, dim in dims.items():
        vals = [settings[r].get(d) for r in runs]
        if any(v is None for v in vals):
            continue
        if dim["kind"] == "presence":
            pres = {v not in (False, "absent") for v in vals}
            if len(pres) == 1:
                conds[d] = {"present": pres.pop()}
        elif dim["kind"] == "boolean":
            if len(set(vals)) == 1:
                conds[d] = vals[0]
        else:
            uniq = [v for v in dim["values"] if v in set(vals)]
            if len(uniq) < len(dim["values"]):
                conds[d] = uniq[0] if len(uniq) == 1 else uniq
    return conds


def _ranges(conds, neg, settings, dims):
    """Write ordinal lists as upper ranges where no negative contradicts it:
    [postQC, DE, none] becomes {min: postQC}, taking in GSEA, which no run tried."""
    for d, c in list(conds.items()):
        dim = dims[d]
        if dim["kind"] != "ordinal" or isinstance(c, dict):
            continue
        vals = c if isinstance(c, list) else [c]
        lo = min(dim["values"].index(v) for v in vals)
        if lo == 0:
            continue
        rng = dim["values"][lo:]
        trial = dict(conds, **{d: {"min": dim["values"][lo]} if len(rng) > 1 else rng[0]})
        if _excludes(trial, neg, settings, dims):
            conds = trial
    return conds


def _generalise(conds, pos, neg, settings, dims, order):
    """Drop or widen conditions while every negative stays excluded, taking at
    each step the move that covers the most positives (ties: `order`)."""
    rank = {d: i for i, d in enumerate(order)}
    # How many negatives a condition rules out on its own. When moves tie, the
    # least discriminating condition goes first, so the informative one stays:
    # KALLISTO_QUANT, seen in one run, keeps `aligner = kallisto` (rules out
    # every other RNASEQ run) rather than `dtu` (rules out fewer), which the
    # one run happens to share.
    power = {d: sum(holds({"params": {d: c}}, settings[r], dims) is False for r in neg) for d, c in conds.items()}
    while True:
        moves = []
        for d, c in conds.items():
            trial = {k: v for k, v in conds.items() if k != d}
            if _excludes(trial, neg, settings, dims):
                moves.append((_covered(trial, pos, settings, dims), 1, -power.get(d, 0), -rank[d], trial))
            dim = dims[d]
            if dim["kind"] in ("enum", "ordinal") and not isinstance(c, dict):
                vals = c if isinstance(c, list) else [c]
                for v in dim["values"]:
                    if v in vals:
                        continue
                    wider = [x for x in dim["values"] if x in vals or x == v]
                    trial = dict(conds, **{d: wider})
                    gain = _covered(trial, pos, settings, dims)
                    # widen only to reach more positives, never just to generalise
                    if gain > _covered(conds, pos, settings, dims) and _excludes(trial, neg, settings, dims):
                        moves.append((gain, 0, 0, -rank[d], trial))
        if not moves:
            return _ranges(conds, neg, settings, dims)
        moves.sort(key=lambda m: m[:4], reverse=True)
        conds = moves[0][4]


def _orders(dims, n=6):
    keys = list(dims)
    rng = random.Random(0)
    out = [keys, keys[::-1]]
    for _ in range(n):
        out.append(rng.sample(keys, len(keys)))
    return out


def _conjunction(pos, neg, settings, dims):
    """Smallest conjunctions true on every positive and false on every
    negative, from several generalisation orders, best first; [] if none."""
    start = _specific(pos, settings, dims)
    if not _excludes(start, neg, settings, dims):
        return []
    found = []
    for order in _orders(dims):
        c = _generalise(dict(start), pos, neg, settings, dims, order)
        if c not in found:
            found.append(c)
    n = min(len(c) for c in found)
    return sorted([c for c in found if len(c) == n], key=lambda c: sum(_size(v) for v in c.values()))


def _term(seed, pos, neg, settings, dims):
    """One alternative of an `any`: the seed run's exact settings, generalised
    towards covering as many positives as possible."""
    conds = _specific([seed], settings, dims)
    if not _excludes(conds, neg, settings, dims):
        return None                        # even fully specific, a negative matches: inexpressible
    return _generalise(conds, pos, neg, settings, dims, list(dims))


def _merge(terms, dims):
    """Merge alternatives that differ in exactly one enum dimension."""
    changed = True
    while changed:
        changed = False
        for a, b in itertools.combinations(range(len(terms)), 2):
            ta, tb = terms[a], terms[b]
            if set(ta) != set(tb):
                continue
            diff = [d for d in ta if ta[d] != tb[d]]
            if len(diff) == 1 and dims[diff[0]]["kind"] in ("enum", "ordinal") \
                    and not isinstance(ta[diff[0]], dict) and not isinstance(tb[diff[0]], dict):
                d = diff[0]
                va = ta[d] if isinstance(ta[d], list) else [ta[d]]
                vb = tb[d] if isinstance(tb[d], list) else [tb[d]]
                vals = [v for v in dims[d]["values"] if v in va or v in vb]
                terms[a] = dict(ta, **{d: vals[0] if len(vals) == 1 else vals})
                del terms[b]
                changed = True
                break
    return terms


def infer(observed, settings, dims, alternatives=False):
    """observed: run ids the element appeared in. settings: run id -> {dim: value}.
    dims: dimension id -> record. Returns (predicate or None, ok), or with
    alternatives=True (predicate, ok, others): `others` are further predicates
    of the same size that fit the runs equally well. More than one means the
    runs do not decide between them; a run on which they disagree would."""
    runs = list(settings)
    pos = [r for r in runs if r in observed]
    neg = [r for r in runs if r not in observed]
    others = []
    if not neg:
        return (None, True, []) if alternatives else (None, True)
    if not pos:
        return ({"params": {}}, False, []) if alternatives else ({"params": {}}, False)
    conjs = _conjunction(pos, neg, settings, dims)
    if conjs:
        pred = {"params": conjs[0]}
        # alternatives that mean the same ({min: postQC} and [postQC, DE, GSEA, none]) are one
        kept = [pred]
        for c in conjs[1:]:
            p = {"params": c}
            if not any(_equivalent(p, k, dims) for k in kept):
                kept.append(p)
        others = kept[1:]
    else:
        terms, todo = [], list(pos)
        while todo:
            t = _term(todo[0], pos, neg, settings, dims)
            if t is None:
                return (None, False, []) if alternatives else (None, False)
            terms.append(t)
            todo = [r for r in todo if holds({"params": t}, settings[r], dims) is not True]
        # drop alternatives whose positives the others already cover
        for t in sorted(terms, key=lambda t: _covered(t, pos, settings, dims)):
            rest = [x for x in terms if x is not t]
            if rest and all(any(holds({"params": x}, settings[r], dims) is True for x in rest) for r in pos):
                terms = rest
        terms = _merge(terms, dims)
        shared = {d: c for d, c in terms[0].items() if all(t.get(d) == c for t in terms)}
        rest = [{"params": {d: c for d, c in t.items() if d not in shared}} for t in terms]
        pred = ({"params": shared} if shared else {})
        if len(rest) == 1:
            pred.setdefault("params", {}).update(rest[0]["params"])
        else:
            pred["any"] = rest
    ok = all((holds(pred, settings[r], dims) is True) == (r in observed) for r in runs)
    return (pred, ok, others) if alternatives else (pred, ok)
