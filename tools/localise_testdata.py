"""Download a test profile's remote files once, for previews that never fetch.

    python3 localise_testdata.py CONFIG DEST [--extra "--transcript_fasta null"]

Run in WSL. Every `param = 'https://...'` in CONFIG (e.g. a pipeline's
conf/test.config) is downloaded into DEST. A text file that itself lists URLs
(a samplesheet of remote FASTQs, a BBSplit list of remote FASTAs) has those
downloaded too and is rewritten to point at the local copies. Writes
DEST/fixed_args.txt: `--param /local/path ...` for every downloaded param,
plus --extra, for tools/adaptive.py --fixed.

Why: a preview checks that its input files exist while it builds the graph.
With remote test data that is dozens of HTTP requests per preview, and with
four previews at a time some of them hang (nf-core/rnaseq 3.27: a preview
stalled for 16 minutes after HTTP 404 retries). Local files make previews
faster and remove the stalls.
"""
import argparse, os, re, shlex, sys, urllib.request

URL = re.compile(r"https?://[^\s'\",]+")
ASSIGN = re.compile(r"^\s*(?:params\.)?(\w+)\s*=\s*['\"](https?://[^'\"]+)['\"]")
TEXT = (".csv", ".tsv", ".txt", ".yml", ".yaml", ".json")


def fetch(url, dest_dir, seen):
    """Download url into dest_dir (once), keeping its name; rewrite listed URLs
    in a text file. Returns the local path."""
    if url in seen:
        return seen[url]
    name = url.rstrip("/").split("/")[-1].split("?")[0] or "download"
    path = os.path.join(dest_dir, name)
    n = 1
    while os.path.exists(path) and path not in seen.values():
        root, ext = os.path.splitext(name)
        path = os.path.join(dest_dir, f"{root}_{n}{ext}")
        n += 1
    seen[url] = path
    if not os.path.exists(path):
        print(f"  {url}\n    -> {path}")
        urllib.request.urlretrieve(url, path)
    if path.endswith(TEXT):
        text = open(path, encoding="utf-8", errors="replace").read()
        urls = URL.findall(text)
        if urls:
            sub = os.path.join(dest_dir, os.path.splitext(os.path.basename(path))[0] + "_files")
            os.makedirs(sub, exist_ok=True)
            for u in urls:
                text = text.replace(u, fetch(u, sub, seen))
            open(path, "w", encoding="utf-8").write(text)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    ap.add_argument("dest")
    ap.add_argument("--extra", default="", help="args appended to fixed_args.txt as they are")
    a = ap.parse_args()
    dest = os.path.abspath(os.path.expanduser(a.dest))
    os.makedirs(dest, exist_ok=True)
    seen, args = {}, []
    # a param set in --extra wins: it is not downloaded (a command-line value
    # would override the params file that carries `--transcript_fasta null`)
    overridden = set(re.findall(r"--(\w+)", a.extra))
    for line in open(a.config, encoding="utf-8"):
        m = ASSIGN.match(line.split("//", 1)[0] if "://" not in line else line)
        if m and m.group(1) not in overridden:
            local = fetch(m.group(2), dest, seen)
            args.append(f"--{m.group(1)} {shlex.quote(local)}")
    if a.extra:
        args.append(a.extra)
    out = os.path.join(dest, "fixed_args.txt")
    open(out, "w", encoding="utf-8").write(" ".join(args) + "\n")
    print(f"\n{len(seen)} files in {dest}; fixed args in {out}:\n{' '.join(args)}")


if __name__ == "__main__":
    main()
