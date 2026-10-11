"""Reference evaluator for channel-model predicates (schema 0.1).

Three-valued: every predicate evaluates to True, False or None (unknown).
A setting is unknown when the viewer leaves it at "any" (None), when it holds
a list that only partly matches (several routes ticked), or when the
predicate has a `data` clause, which no setting can decide.

`holds` is the quick Kleene evaluation. It is sound (a True or False from it
is always right) but can say None where the settings do decide the answer.
`given` is exact: when `holds` says None it enumerates the settings still at
"any" that the predicate mentions, keeps the combinations consistent with
what the explicit settings imply (a dimension's `implies`), and answers True
or False only if every such combination agrees.

The viewer draws an element unless `when` is definitely False, and marks it
starved only when `flows_when` is definitely False among the combinations
where the element exists. The JavaScript viewer must agree with this file;
tools/js_parity.py checks that.
"""
import itertools


def _and(vals):
    vals = list(vals)
    if any(v is False for v in vals): return False
    if all(v is True for v in vals): return True
    return None

def _or(vals):
    vals = list(vals)
    if any(v is True for v in vals): return True
    if all(v is False for v in vals): return False
    return None

def _not(v):
    return None if v is None else not v


def condition(dim, cond, setting):
    """One dimension's condition against one setting. dim is the dimension record."""
    if setting is None:
        return None
    if isinstance(setting, list):                 # several values ticked at once
        res = [condition(dim, cond, s) for s in setting]
        if all(r is True for r in res): return True
        if all(r is False for r in res): return False
        return None
    kind = dim["kind"]
    if isinstance(cond, dict) and "present" in cond:
        return (setting is not False and setting != "absent") == cond["present"]
    if isinstance(cond, dict):                    # {min}/{max} on an ordinal
        order = dim["values"]
        pos = order.index(setting)
        if "min" in cond and pos < order.index(cond["min"]): return False
        if "max" in cond and pos > order.index(cond["max"]): return False
        return True
    if isinstance(cond, list):
        return setting in cond
    if kind == "boolean":
        return bool(setting) == bool(cond)
    return setting == cond


def holds(pred, settings, dims):
    """Kleene evaluation. pred: a predicate (or None). settings: dimension id ->
    value, list or None. dims: dimension id -> dimension record."""
    if not pred:
        return True
    parts = [condition(dims[d], c, settings.get(d)) for d, c in pred.get("params", {}).items()]
    if "any" in pred:
        parts.append(_or(holds(a, settings, dims) for a in pred["any"]))
    if "not" in pred:
        parts.append(_not(holds(pred["not"], settings, dims)))
    if pred.get("data"):
        parts.append(None)
    return _and(parts)


def variables(pred, out=None):
    """Dimension ids a predicate mentions."""
    out = set() if out is None else out
    if pred:
        out.update(pred.get("params", {}))
        for a in pred.get("any", []): variables(a, out)
        variables(pred.get("not"), out)
    return out

def domain(dim):
    if dim["kind"] == "boolean": return [True, False]
    if dim["kind"] == "presence": return ["present", "absent"]
    return list(dim["values"])

def implied(settings, dims):
    """What the explicitly set dimensions imply. Not chained: an implied value
    does not bring in that dimension's own implication."""
    return [d["implies"] for k, d in dims.items() if d.get("implies") and settings.get(k) is not None]


def given(pred, settings, dims, conds=()):
    """Exact value of pred over the completions of the unset dimensions that
    satisfy every predicate in conds (each must not be definitely False)."""
    r = holds(pred, settings, dims)
    if r is not None:
        return r
    free = sorted(d for d in variables(pred).union(*[variables(c) for c in conds]) if settings.get(d) is None)
    if not free:
        return None
    seen, any_ok = set(), False
    for combo in itertools.product(*(domain(dims[d]) for d in free)):
        s2 = dict(settings, **dict(zip(free, combo)))
        if any(holds(c, s2, dims) is False for c in conds):
            continue
        any_ok = True
        seen.add(holds(pred, s2, dims))
        if len(seen) > 1:
            return None
    if not any_ok:                    # contradictory settings: fall back to the quick answer
        return None
    return seen.pop()


def state(element, settings, dims):
    """Display state: absent, starved, may, flows. See schema/README.md."""
    conds = implied(settings, dims)
    when = element.get("when")
    if given(when, settings, dims, conds) is False:
        return "absent"
    flows = element.get("flows_when")
    f = given(flows, settings, dims, conds + ([when] if when else []))
    if f is False:
        return "starved"
    if f is None and _has_data(flows):
        return "may"
    return "flows"

def _has_data(pred):
    if not pred: return False
    if pred.get("data"): return True
    return any(_has_data(a) for a in pred.get("any", [])) or _has_data(pred.get("not"))
