"""Align a pipeline's preview DAGs into one union graph with stable node ids.

    python tools/align.py DAG [DAG ...] [-o union.json]

Nextflow numbers DAG nodes by position (v0, v1, ...), so the same operator
gets a different id in every run, and ids shift as soon as anything upstream
is absent. Processes are the anchors: their names never change. Every other
node (operators, and the input and output points) is matched across runs by
evidence:

  - neighbours already matched, joined by an edge with the same label
    (3 points each);
  - its upstream signature: a hash of the chain above it, out to the nearest
    processes, edge labels included (2 points);
  - its downstream signature, the same looking down (2 points).

Runs are merged widest first. In each round every unmatched node of the run is
scored against every union node of the same type not yet used by this run; the
strongest pairs are accepted first, and matches spread outward from the
processes over the rounds. A node with no evidence for any union node becomes
a new union node. Both signatures matter: a channel reassigned inside an `if`
keeps its downstream but changes its upstream (fetchngs' samplesheet chain),
and a mix chain with a process missing keeps neither for long, which is what
the neighbour evidence is for.

The union graph records, for every node and edge, the runs it was observed in.
That is what Phase 2 turns into `when` predicates.
"""
import argparse, collections, hashlib, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dot

W_NEIGHBOUR, W_SIG = 3, 2


def h(s):
    return hashlib.sha1(s.encode()).hexdigest()[:12]


class Run:
    """One DAG: nodes, labelled edges, and both signatures for every node."""

    def __init__(self, name, path):
        self.name = name
        nodes, edges = dot.parse(path)
        self.nodes = nodes
        self.edges = edges
        self.order = {v: int(v[1:]) for v in nodes}
        self.preds, self.succs = collections.defaultdict(list), collections.defaultdict(list)
        for a, b, l in edges:
            self.preds[b].append((a, l))
            self.succs[a].append((b, l))
        self._up, self._down = {}, {}
        self._type = {v: (n["label"] if n["kind"] == "process" else ("op:" + n["label"] if n["kind"] == "operator" else "point"))
                      for v, n in nodes.items()}
        # position among the run's nodes of the same type, 0..1: a tie-break only
        by_type = collections.defaultdict(list)
        for v in nodes:
            by_type[self._type[v]].append(v)
        self.rank = {}
        for vs in by_type.values():
            vs.sort(key=lambda v: self.order[v])
            for i, v in enumerate(vs):
                self.rank[v] = i / max(1, len(vs) - 1)

    def type(self, v):
        return self._type[v]

    def up(self, v):
        if v not in self._up:
            if self.nodes[v]["kind"] == "process":
                self._up[v] = "P:" + self.nodes[v]["label"]
            else:
                parts = sorted(f"{l}<{self.up(p)}" for p, l in self.preds[v])
                self._up[v] = h("U|" + self.type(v) + "|" + ",".join(parts)) if parts else "in:" + self.type(v)
        return self._up[v]

    def down(self, v):
        if v not in self._down:
            if self.nodes[v]["kind"] == "process":
                self._down[v] = "P:" + self.nodes[v]["label"]
            else:
                parts = sorted(f"{l}>{self.down(s)}" for s, l in self.succs[v])
                self._down[v] = h("D|" + self.type(v) + "|" + ",".join(parts)) if parts else "out:" + self.type(v)
        return self._down[v]


class Union:
    def __init__(self):
        self.nodes = {}          # uid -> {type, kind, label, ups, downs, observed, rank}
        self.preds = collections.defaultdict(set)   # uid -> {(uid, label)}
        self.succs = collections.defaultdict(set)
        self.edges = {}          # (uid, uid, label, k) -> observed runs
        self.runs = []
        self.mapping = {}        # run name -> {vid: uid}
        self._n = 0

    def _new(self, run, v):
        self._n += 1
        uid = run.nodes[v]["label"] if run.nodes[v]["kind"] == "process" else f"n{self._n}"
        self.nodes[uid] = {"type": run.type(v), "kind": run.nodes[v]["kind"], "label": run.nodes[v]["label"],
                           "ups": set(), "downs": set(), "up_anchors": set(), "down_anchors": set(),
                           "observed": [], "rank": self._rank(run, v)}
        return uid

    @staticmethod
    def _anchor(run, x, adj, memo):
        """The process reached from x by following single-neighbour links in one
        direction: x itself if a process, else the anchor of its only
        predecessor (or successor). None at a fork, a merge or an end."""
        if x not in memo:
            if run.nodes[x]["kind"] == "process":
                memo[x] = run.nodes[x]["label"]
            else:
                nb = adj[x]
                memo[x] = None
                memo[x] = Union._anchor(run, nb[0][0], adj, memo) if len(nb) == 1 else None
        return memo[x]

    def _run_anchors(self, run, v, direction, memo):
        """Anchors of v's inputs (or outputs), with the edge label."""
        adj = run.preds if direction == "up" else run.succs
        out = set()
        for x, l in adj[v]:
            a = self._anchor(run, x, adj, memo)
            if a: out.add((a, l))
        return out

    @staticmethod
    def _rank(run, v):
        return run.rank[v]

    def add(self, run):
        self.runs.append(run.name)
        m = {}
        # processes: by name
        for v, n in run.nodes.items():
            if n["kind"] == "process":
                m[v] = n["label"] if n["label"] in self.nodes else self._new(run, v)
        used = set(m.values())
        todo = [v for v in run.nodes if v not in m]
        # Fast path: a node whose type and both signatures were seen on exactly
        # one union node is that node. Late in a large matrix almost every node
        # is matched here, leaving only what is new for the scoring below.
        seen_sig = collections.defaultdict(set)
        for uid, u in self.nodes.items():
            for up in u["ups"]:
                for down in u["downs"]:
                    seen_sig[(u["type"], up, down)].add(uid)
        claims = collections.defaultdict(list)
        for v in todo:
            c = seen_sig.get((run.type(v), run.up(v), run.down(v)), ())
            if len(c) == 1:
                claims[next(iter(c))].append(v)
        for uid, vs in claims.items():
            if len(vs) == 1 and uid not in used:
                m[vs[0]] = uid
                used.add(uid)
        todo = [v for v in todo if v not in m]
        by_type = collections.defaultdict(list)
        for uid, u in self.nodes.items():
            by_type[u["type"]].append(uid)
        # The processes a node's inputs and outputs anchor to: the strongest
        # identity a non-process node has.
        mu, md = {}, {}
        rp = {v: self._run_anchors(run, v, "up", mu) for v in todo}
        rs = {v: self._run_anchors(run, v, "down", md) for v in todo}
        while todo:
            pairs = []
            for v in todo:
                t, up, down, rank = run.type(v), run.up(v), run.down(v), self._rank(run, v)
                for uid in by_type[t]:
                    if uid in used:
                        continue
                    u = self.nodes[uid]
                    # Inputs (or outputs) anchored to different processes: different
                    # operators, e.g. one collect per aligner, each in its own if
                    # block, or the versions mix for each route. They never meet in
                    # one run, so only this rule keeps them apart.
                    up_, dn_ = u["up_anchors"], u["down_anchors"]
                    if (rp[v] and up_ and not rp[v] & up_) or (rs[v] and dn_ and not rs[v] & dn_):
                        continue
                    s = 0
                    for p, l in run.preds[v]:
                        if p in m and (m[p], l) in self.preds[uid]: s += W_NEIGHBOUR
                    for c, l in run.succs[v]:
                        if c in m and (m[c], l) in self.succs[uid]: s += W_NEIGHBOUR
                    # A node with nothing above it (a source, an input point) has a
                    # trivial upstream signature shared by every such node: no
                    # evidence. Likewise downstream for sinks.
                    if up in u["ups"] and not up.startswith("in:"): s += W_SIG
                    if down in u["downs"] and not down.startswith("out:"): s += W_SIG
                    if s:
                        pairs.append((-s, abs(rank - u["rank"]), v, uid))
            if not pairs:
                break
            pairs.sort()
            took = 0
            best = -pairs[0][0]
            for neg, _, v, uid in pairs:
                # Accept only the strongest evidence this round; weaker pairs are
                # re-scored next round, once more neighbours are known.
                if -neg < best or v in m or uid in used:
                    continue
                m[v] = uid; used.add(uid); took += 1
            todo = [v for v in todo if v not in m]
            if not took:
                break
        for v in todo:
            m[v] = self._new(run, v)
        # record
        mu, md = {}, {}
        for v, uid in m.items():
            u = self.nodes[uid]
            u["observed"].append(run.name)
            u["ups"].add(run.up(v)); u["downs"].add(run.down(v))
            u["up_anchors"] |= self._run_anchors(run, v, "up", mu)
            u["down_anchors"] |= self._run_anchors(run, v, "down", md)
        seen = collections.Counter()
        for a, b, l in run.edges:
            key = (m[a], m[b], l)
            k = seen[key]; seen[key] += 1           # parallel edges with the same label
            self.edges.setdefault(key + (k,), []).append(run.name)
            self.preds[m[b]].add((m[a], l)); self.succs[m[a]].add((m[b], l))
        self.mapping[run.name] = m

    # ---- readable ids --------------------------------------------------------
    def anchors(self, uid, direction):
        """Nearest processes (or labelled edges) upstream or downstream of uid."""
        adj = self.preds if direction == "up" else self.succs
        seen, stack, found = {uid}, [uid], set()
        while stack:
            cur = stack.pop()
            for nxt, l in adj[cur]:
                if self.nodes[nxt]["kind"] == "process":
                    found.add(self.nodes[nxt]["label"].split(":")[-1])
                elif l:
                    found.add(l)
                elif nxt not in seen:
                    seen.add(nxt); stack.append(nxt)
        return sorted(found)

    def readable_ids(self):
        base = {}
        for uid, u in self.nodes.items():
            if u["kind"] == "process":
                continue
            up, down = self.anchors(uid, "up"), self.anchors(uid, "down")
            t = u["type"][3:] if u["type"].startswith("op:") else "point"
            base[uid] = f"{t}@{'+'.join(up[:2]) or 'start'}>{'+'.join(down[:2]) or 'end'}"
        rename, count = {}, collections.Counter()
        for uid in sorted(base, key=lambda x: (base[x], self.nodes[x]["rank"])):
            k = count[base[uid]]; count[base[uid]] += 1
            rename[uid] = base[uid] + (f"#{k}" if k or list(base.values()).count(base[uid]) > 1 else "")
        return rename

    def to_json(self):
        rename = self.readable_ids()
        rid = lambda u: rename.get(u, u)
        return {
            "runs": self.runs,
            "nodes": [{"id": rid(uid), "kind": u["kind"], "type": u["type"], "label": u["label"], "observed_in": u["observed"]}
                      for uid, u in self.nodes.items()],
            "edges": [{"from": rid(a), "to": rid(b), "label": l, "observed_in": obs} for (a, b, l, k), obs in self.edges.items()],
            "mapping": {r: {v: rid(u) for v, u in m.items()} for r, m in self.mapping.items()},
        }


def align(paths):
    """paths: {run name: DOT path}. Returns a Union."""
    runs = [Run(n, p) for n, p in paths.items()]
    # Canonical order, widest first, ties by name. The result is deterministic
    # but not fully order-independent: output points of unconsumed emits are
    # matched by position only, and a union node's anchors grow as runs merge
    # (see test_align.py's order check).
    runs.sort(key=lambda r: (-len(r.nodes), r.name))
    u = Union()
    for r in runs:
        u.add(r)
    return u


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dags", nargs="+")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    u = align({os.path.splitext(os.path.basename(p))[0]: p for p in a.dags})
    j = u.to_json()
    kinds = collections.Counter(n["kind"] for n in j["nodes"])
    print(f"{len(j['runs'])} runs -> {len(j['nodes'])} nodes ({dict(kinds)}), {len(j['edges'])} edges")
    if a.out:
        json.dump(j, open(a.out, "w", encoding="utf-8"), indent=1)
        print("wrote", a.out)
