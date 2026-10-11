"""Read Nextflow -with-dag DOT files.

Nextflow writes each node declaration again before every edge that uses it,
and the order of blocks varies between runs, so everything here works on
sets and multisets, never on file order. Node ids (v0, v1, ...) are
positional and are not stable between runs; they are kept only to join edges
to nodes within one file.
"""
import collections, re

NODE = re.compile(r'^(v\d+)\s*\[(.*)\];\s*$')
EDGE = re.compile(r'^(v\d+)\s*->\s*(v\d+)(?:\s*\[label="([^"]*)"\])?;\s*$')
ATTR = re.compile(r'(\w+)=("([^"]*)"|[^,\]]+)')


def parse(path):
    """Returns (nodes, edges). nodes: id -> {"kind", "label"}. edges: list of (from, to, label)."""
    nodes, edges = {}, []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        m = EDGE.match(line)
        if m:
            edges.append((m.group(1), m.group(2), m.group(3) or ""))
            continue
        m = NODE.match(line)
        if m:
            attrs = {k: (q if q is not None else v) for k, v, q in
                     ((a.group(1), a.group(2), a.group(3)) for a in ATTR.finditer(m.group(2)))}
            if attrs.get("xlabel"):
                kind, label = "operator", attrs["xlabel"]
            elif attrs.get("shape") == "point":
                kind, label = "point", ""
            else:
                kind, label = "process", attrs.get("label", "")
            nodes[m.group(1)] = {"kind": kind, "label": label}
    return nodes, edges


def signature(node):
    """What a node can be matched on across runs without its id."""
    if node["kind"] == "process": return node["label"]
    if node["kind"] == "operator": return "op:" + node["label"]
    return "point"


def summary(path):
    """Multisets that a model's prediction for this run can be compared with."""
    nodes, edges = parse(path)
    return {
        "processes": collections.Counter(n["label"] for n in nodes.values() if n["kind"] == "process"),
        "operators": collections.Counter(n["label"] for n in nodes.values() if n["kind"] == "operator"),
        "edges": collections.Counter((signature(nodes[a]), signature(nodes[b]), l) for a, b, l in edges),
    }
