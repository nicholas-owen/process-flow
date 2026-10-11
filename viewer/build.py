"""Build a self-contained channel-viewer page from a channel model.

    python viewer/build.py fixtures/fetchngs.json
    python viewer/build.py fixtures/rnaseq-flow.json --logo ../rnaseq-flow/assets/rnaseq-flow_logo.svg
    python viewer/build.py MODEL.json -o somewhere/page.html

Writes out/<model name>.html by default. The page needs no network: the
model, dagre and the optional logo are all inlined.

Placeholders filled in viewer/template.html:
  __TITLE__      the page title
  __PFLOGO__     process-flow's own logo (assets/process-flow_logo.svg), top left
  __LOGO__       an <img> with the pipeline's logo as a data URI, or nothing
  __DATA__       the model JSON
  /*__DAGRE__*/  viewer/vendor/dagre.min.js

From Python: `from build import validate, page`.
"""
import argparse, base64, html, json, mimetypes, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def validate(model):
    """Schema errors as strings; [] if valid, None if jsonschema is not installed."""
    try:
        import jsonschema
    except ImportError:
        return None
    schema = json.load(open(os.path.join(ROOT, "schema", "channels.schema.json"), encoding="utf-8"))
    return [f"{e.json_path}: {e.message[:150]}" for e in jsonschema.Draft202012Validator(schema).iter_errors(model)]


def img(path, alt):
    mime = mimetypes.guess_type(path)[0] or "image/svg+xml"
    uri = f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode("ascii")
    return f'<img src="{uri}" alt="{html.escape(alt)}">'


def page(model, logo=None):
    """The HTML page for a model."""
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    dagre = open(os.path.join(HERE, "vendor", "dagre.min.js"), encoding="utf-8").read()
    pf_logo = img(os.path.join(ROOT, "assets", "process-flow_logo.svg"), "process-flow")
    logo_img = img(logo, model["pipeline"]["name"]) if logo else ""
    # The JSON sits inside a <script> block: a literal "</script>" in a note would
    # end it early, so every "</" is escaped the standard way.
    data = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = html.escape(f'{model["pipeline"]["name"]}: channels')
    for ph in ("__TITLE__", "__PFLOGO__", "__LOGO__", "__DATA__", "/*__DAGRE__*/"):
        assert tpl.count(ph) == 1, f"placeholder {ph} must appear exactly once in the template"
    # dagre last: its minified source could contain anything, including a placeholder name.
    return (tpl.replace("__TITLE__", title).replace("__PFLOGO__", pf_logo).replace("__LOGO__", logo_img)
               .replace("__DATA__", data).replace("/*__DAGRE__*/", dagre))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", help="channel model JSON (schema 0.1)")
    ap.add_argument("-o", "--out", help="output HTML (default: out/<model name>.html)")
    ap.add_argument("--logo", help="image to show in the header (SVG or PNG)")
    ap.add_argument("--no-validate", action="store_true", help="skip schema validation even if jsonschema is installed")
    args = ap.parse_args()
    model = json.load(open(args.model, encoding="utf-8"))
    if not args.no_validate:
        errs = validate(model)
        if errs is None:
            print("note: jsonschema not installed, model not validated", file=sys.stderr)
        elif errs:
            for e in errs[:10]: print(f"  {e}", file=sys.stderr)
            sys.exit(f"{args.model}: {len(errs)} schema errors")
    html_page = page(model, args.logo)
    out = args.out or os.path.join(ROOT, "out", os.path.splitext(os.path.basename(args.model))[0] + ".html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_page)
    shown = os.path.relpath(out, ROOT) if os.path.splitdrive(os.path.abspath(out))[0] == os.path.splitdrive(ROOT)[0] else out
    print(f"wrote {shown}: {len(html_page):,} bytes; {len(model['nodes'])} nodes, {len(model['edges'])} edges")


if __name__ == "__main__":
    main()
