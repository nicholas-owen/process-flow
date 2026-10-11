"""Fixture #2: nf-core/fetchngs 1.13.0, modelled by hand from the source.

Source read from working_docs/fetchngs-src/ (a copy of the 1.13.0 clone,
revision 955c892d80). Writes fixtures/fetchngs.json, then checks it:

  1. it validates against schema/channels.schema.json (if jsonschema is
     installed);
  2. for each of the 8 preview runs in working_docs/fetchngs-preview/, the
     processes, operators and edges the model predicts under that run's
     settings equal the DOT's, as multisets (edges matched on endpoint kind
     or name plus edge label, since DOT ids are positional);
  3. a coverage count of where every contents field came from.

    python fixtures/fetchngs_spec.py

Every node and edge here was placed by reading the code. The `dot` value on
an edge is the label the DAG prints for it, kept only for check 2.
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dot
from predicates import holds

OUT = os.path.join(HERE, "fetchngs.json")
PREVIEW = os.path.join(ROOT, "working_docs", "fetchngs-preview")

PI = ["PIPELINE_INITIALISATION"]
FN = ["NFCORE_FETCHNGS", "FETCHNGS"]
SRA = FN + ["FASTQ_DOWNLOAD_PREFETCH_FASTERQDUMP_SRATOOLS"]
CSV = FN + ["CHANNEL_SRA_CREATE_CSV"]
WF = "workflows/fetchngs.nf"
CSVF = "subworkflows/local/channel_sra_create_csv/main.nf"
SRAF = "subworkflows/nf-core/fastq_download_prefetch_fasterqdump_sratools/main.nf"
UTIL = "subworkflows/local/utils_nfcore_fetchngs_pipeline/main.nf"

# ---- dimensions and predicates ---------------------------------------------
dimensions = [
    {"id": "download_method", "param": "download_method", "kind": "enum",
     "values": ["aspera", "fastq-dl", "ftp", "sratools"], "default": "ftp", "source": "nextflow_schema.json",
     "implies": {"params": {"skip_fastq_download": False}},
     "description": "Chosen per run inside a branch closure, so it changes what flows, never the graph."},
    {"id": "skip_fastq_download", "param": "skip_fastq_download", "kind": "boolean", "default": False,
     "source": "nextflow_schema.json", "description": "An if around every download route (workflows/fetchngs.nf:60)."},
    {"id": "sample_mapping_fields", "param": "sample_mapping_fields", "kind": "presence", "default": "present",
     "source": "nextflow_schema.json", "description": "Has a default; unsetting it starves MULTIQC_MAPPINGS_CONFIG through a filter on the value."},
]
DIMS = {d["id"]: d for d in dimensions}

DL = {"params": {"skip_fastq_download": False}}       # exists only when downloading
SKIP = {"params": {"skip_fastq_download": True}}

HAS_ASP = {"expr": "meta.fastq_aspera", "text": "the run has an Aspera link"}
NO_ASP = {"expr": "!meta.fastq_aspera", "text": "the run has no Aspera link"}
HAS_FTP = {"expr": "meta.fastq_1", "text": "the run has an FTP link"}
HAS_ANY = {"expr": "meta.fastq_aspera || meta.fastq_1", "text": "the run has an Aspera or an FTP link"}
NO_LINKS = {"expr": "!meta.fastq_aspera && !meta.fastq_1", "text": "the run has neither an Aspera nor an FTP link"}

# Worked out from the closure at workflows/fetchngs.nf:62-84. Later ifs
# override earlier ones; the Phase 2 closure evaluator has to reproduce these.
FLOW = {
    "aspera":   {"params": {"download_method": "aspera"}, "data": [HAS_ASP]},
    "fastq-dl": {"params": {"download_method": "fastq-dl"}, "data": [HAS_ANY]},
    "ftp":      {"any": [{"params": {"download_method": "ftp"}, "data": [HAS_ANY]},
                         {"params": {"download_method": "aspera"}, "data": [NO_ASP, HAS_FTP]}]},
    "sratools": {"any": [{"params": {"download_method": "sratools"}},
                         {"data": [NO_LINKS]}]},
}
MAPPINGS = {"params": {"sample_mapping_fields": {"present": True}}}

# ---- contents shorthands ---------------------------------------------------
META_KEYS = ["id", "run_accession", "sample_accession", "single_end", "fastq_1", "fastq_2",
             "md5_1", "md5_2", "fastq_aspera"]
META_TEXT = ("Keys the code reads; the full set is every column sra_runinfo_to_ftp.py writes, "
             "which includes the --ena_metadata_fields.")

def C(shape=None, card=None, per=None, meta="none", files=None, src="annotated", text=None, **from_):
    """Contents. src is the provenance for every field given, unless from_ overrides one.
    A module declaration gives shape and files, and says whether there is a meta
    map, but never which keys it holds or how many items arrive: with
    src="declared", meta keys and cardinality stay "annotated"."""
    c = {}
    if shape is not None: c["shape"] = shape
    if meta != "none": c["meta"] = meta
    if card:
        c["cardinality"] = {"kind": card}
        if per: c["cardinality"]["per"] = per
        if text: c["cardinality"]["text"] = text
    if files: c["files"] = files
    def prov(k):
        if k in from_: return from_[k]
        if src == "declared" and (k == "cardinality" or (k == "meta" and meta is not None)): return "annotated"
        return src
    c["from"] = {k: prov(k) for k in ("shape", "meta", "cardinality", "files") if k in c}
    return c

def run_meta(added=None, text=META_TEXT):
    m = {"keys": META_KEYS, "text": text}
    if added: m["added"] = added
    return m

VERSIONS = C("[process, tool, version]", "queue", "task", meta=None, src="declared",
             files="none: values, collected through channel.topic('versions')")

# ---- nodes -----------------------------------------------------------------
nodes, edges = [], []

def N(id, kind, label, path=None, source=None, when=None, flows=None, op=None, closure=None,
      module=None, category="shared", lane="main", notes=None):
    n = {"id": id, "kind": kind, "label": label}
    if path: n["path"] = path
    if module: n["module"] = module
    if op or closure:
        n["operator"] = {k: v for k, v in (("type", op), ("closure", closure)) if v}
    if source: n["source"] = source
    if when: n["when"] = when
    n["when_from"] = "annotated"
    if flows:
        n["flows_when"] = flows
        n["flows_when_from"] = "annotated"
    n["lane"] = lane
    n["category"] = category
    if notes: n["notes"] = notes
    nodes.append(n)
    return id

def P(name, sub=FN, module=None, **kw):
    path = sub + [name]
    return N(":".join(path), "process", name, path=path, module=module, source=module, **kw)

def E(frm, to, name=None, dot="", contents=None, when=None, flows=None, operator=None, lane="main", notes=None):
    e = {"id": f"{frm}->{to}" + (f"[{name}]" if name else ""), "from": frm, "to": to}
    if name: e["name"] = name
    if operator: e["operator"] = operator
    if contents: e["contents"] = contents
    if when: e["when"] = when
    e["when_from"] = "annotated"
    if flows:
        e["flows_when"] = flows
        e["flows_when_from"] = "annotated"
    e["lane"] = lane
    if notes: e["notes"] = notes
    e["_dot"] = dot
    edges.append(e)

# Inputs and the id channel
ids_src = N("PIPELINE_INITIALISATION/channel.fromList", "source", "channel.fromList(samplesheetToList(--input))",
            path=PI, source=f"{UTIL}:129", op="channel.fromList", category="input",
            notes="Reads --input against assets/schema_input.json. --input itself is not drawn: it is read in a closure, not passed as a channel.")
ids_u = N("PIPELINE_INITIALISATION/unique@ids", "operator", "unique", path=PI, source=f"{UTIL}:130", op="unique", category="input")
fields = N("in.ena_metadata_fields", "param", "--ena_metadata_fields", path=FN, source="main.nf:43", category="input",
           notes="'' when unset, which the script reads as its default field list.")

p_ids = P("SRA_IDS_TO_RUNINFO", module="modules/local/sra_ids_to_runinfo/main.nf")
p_ftp_tsv = P("SRA_RUNINFO_TO_FTP", module="modules/local/sra_runinfo_to_ftp/main.nf")
o_filter = N("FETCHNGS/filter@runinfo", "operator", "filter { row -> row.size() > 0 }", path=FN, source=f"{WF}:55", op="filter")
o_split = N("FETCHNGS/splitCsv@runinfo", "operator", "splitCsv(header: true, sep: '\\t')", path=FN, source=f"{WF}:56", op="splitCsv")
o_se = N("FETCHNGS/map@single_end", "operator", "map { meta -> meta + [single_end: meta.single_end.toBoolean()] }",
         path=FN, source=f"{WF}:57", op="map")
o_uniq = N("FETCHNGS/unique@ch_sra_metadata", "operator", "unique", path=FN, source=f"{WF}:58", op="unique")

# The download routes
o_branch = N("FETCHNGS/branch@ch_sra_metadata", "operator", "branch: aspera / fastqdl / ftp / sratools", path=FN,
             source=f"{WF}:62-84", op="branch", when=DL,
             closure="final_download_method from download_method and the run's links; each branch returns its own shape",
             notes="Every route is wired in every run. download_method only decides which route each run takes, so comparing preview DAGs cannot see it; the routes' flows_when come from reading this closure.")
p_ftp = P("SRA_FASTQ_FTP", module="modules/local/sra_fastq_ftp/main.nf", when=DL, flows=FLOW["ftp"], category="ftp")
o_ftp_md5 = N("out.ftp_md5", "output", "*.md5 (FTP)", path=FN, when=DL, flows=FLOW["ftp"], category="ftp",
              source="modules/local/sra_fastq_ftp/main.nf", notes="Emitted and published, read by nothing downstream.")
o_collect = N("FASTQ_DOWNLOAD_PREFETCH_FASTERQDUMP_SRATOOLS/collect@ch_sra_ids", "operator", "ch_sra_ids.collect()", path=SRA,
              source=f"{SRAF}:18", op="collect", when=DL, flows=FLOW["sratools"], category="sratools",
              notes="Assumed: collect on an empty channel emits nothing, so CUSTOM_SRATOOLSNCBISETTINGS is starved off the sratools route. Not yet confirmed on a run.")
p_ncbi = P("CUSTOM_SRATOOLSNCBISETTINGS", sub=SRA, module="modules/nf-core/custom/sratoolsncbisettings/main.nf",
           when=DL, flows=FLOW["sratools"], category="sratools",
           notes="Its only input is a value channel (the collect), so its outputs are value channels too: one settings file paired with every PREFETCH and FASTERQDUMP task.")
dbgap = N("in.dbgap_key", "input", "--dbgap_key", path=FN, source="main.nf:41", when=DL, category="input",
          notes="file(params.dbgap_key) when set, [] otherwise. Never changes the graph; not a dimension.")
p_pre = P("SRATOOLS_PREFETCH", sub=SRA, module="modules/nf-core/sratools/prefetch/main.nf", when=DL, flows=FLOW["sratools"], category="sratools")
p_fqd = P("SRATOOLS_FASTERQDUMP", sub=SRA, module="modules/nf-core/sratools/fasterqdump/main.nf", when=DL, flows=FLOW["sratools"], category="sratools")
user = N("param.aspera_user", "param", "'era-fasp'", path=FN, source=f"{WF}:99", when=DL, category="input",
         notes="A literal in the workflow, not a param.")
p_asp = P("ASPERA_CLI", module="modules/local/aspera_cli/main.nf", when=DL, flows=FLOW["aspera"], category="aspera")
o_asp_md5 = N("out.aspera_md5", "output", "*.md5 (Aspera)", path=FN, when=DL, flows=FLOW["aspera"], category="aspera",
              source="modules/local/aspera_cli/main.nf", notes="Emitted and published, read by nothing downstream.")
p_fdl = P("FASTQDL", module="modules/nf-core/fastqdl/main.nf", when=DL, flows=FLOW["fastq-dl"], category="fastq-dl")
o_fdl_ri = N("out.fastqdl_runinfo", "output", "*-run-info.tsv", path=FN, when=DL, flows=FLOW["fastq-dl"], category="fastq-dl",
             source="modules/nf-core/fastqdl/main.nf")
o_fdl_rm = N("out.fastqdl_runmergers", "output", "*-run-mergers.tsv (optional)", path=FN, when=DL, flows=FLOW["fastq-dl"],
             category="fastq-dl", source="modules/nf-core/fastqdl/main.nf")
o_mix1 = N("FETCHNGS/mix@sratools_reads", "operator", ".mix(FASTQ_DOWNLOAD_PREFETCH_FASTERQDUMP_SRATOOLS.out.reads)", path=FN,
           source=f"{WF}:105", op="mix", when=DL)
o_mix2 = N("FETCHNGS/mix@aspera_fastq", "operator", ".mix(ASPERA_CLI.out.fastq)", path=FN, source=f"{WF}:106", op="mix", when=DL)
o_mix3 = N("FETCHNGS/mix@fastqdl_fastq", "operator", ".mix(FASTQDL.out.fastq)", path=FN, source=f"{WF}:107", op="mix", when=DL)
o_paths = N("FETCHNGS/map@published_paths", "operator", "map { meta, fastq -> meta + [fastq_1: ..., fastq_2: ...] }", path=FN,
            source=f"{WF}:108-112", op="map", when=DL,
            notes="Drops the files and keeps only the meta, with fastq_1 and fastq_2 rewritten to where the FastQ will be published under --outdir. Reassigns ch_sra_metadata, which is why CHANNEL_SRA_CREATE_CSV has a different upstream when downloads are skipped.")

# The samplesheet and mappings
c_map1 = N("CHANNEL_SRA_CREATE_CSV/map@samplesheet_row", "operator", "map { meta -> header + values }", path=CSV,
           source=f"{CSVF}:12-17", op="map", category="samplesheet",
           notes="Columns from buildPipelineMap: sample, fastq_1, fastq_2, any --nf_core_pipeline extras, then the remaining meta. --nf_core_pipeline changes the columns, never the graph.")
c_cf1 = N("CHANNEL_SRA_CREATE_CSV/collectFile@tmp_samplesheet", "operator", "collectFile(name: 'tmp_samplesheet.csv', keepHeader: true, sort: true)",
          path=CSV, source=f"{CSVF}:18", op="collectFile", category="samplesheet")
c_map2 = N("CHANNEL_SRA_CREATE_CSV/map@samplesheet_text", "operator", "map { file -> file.text.tokenize('\\n').join('\\n') }",
           path=CSV, source=f"{CSVF}:19", op="map", category="samplesheet")
c_cf2 = N("CHANNEL_SRA_CREATE_CSV/collectFile@samplesheet", "operator", "collectFile(name: 'samplesheet.csv', storeDir: outdir/samplesheet)",
          path=CSV, source=f"{CSVF}:20", op="collectFile", category="samplesheet")
o_sheet = N("out.samplesheet", "output", "samplesheet/samplesheet.csv", path=FN, source=f"{WF}:143", category="samplesheet")
c_map3 = N("CHANNEL_SRA_CREATE_CSV/map@mappings_row", "operator", "map { meta -> mapping fields header + values }", path=CSV,
           source=f"{CSVF}:24-35", op="map", category="samplesheet",
           notes="Errors out if --sample_mapping_fields names a column the samplesheet does not have.")
c_cf3 = N("CHANNEL_SRA_CREATE_CSV/collectFile@tmp_id_mappings", "operator", "collectFile(name: 'tmp_id_mappings.csv', keepHeader: true, sort: true)",
          path=CSV, source=f"{CSVF}:36", op="collectFile", category="samplesheet")
c_map4 = N("CHANNEL_SRA_CREATE_CSV/map@mappings_text", "operator", "map { file -> file.text.tokenize('\\n').join('\\n') }",
           path=CSV, source=f"{CSVF}:37", op="map", category="samplesheet")
c_cf4 = N("CHANNEL_SRA_CREATE_CSV/collectFile@id_mappings", "operator", "collectFile(name: 'id_mappings.csv', storeDir: outdir/samplesheet)",
          path=CSV, source=f"{CSVF}:38", op="collectFile", category="samplesheet")
o_mfilter = N("FETCHNGS/filter@sample_mapping_fields", "operator", "ch_mappings.filter { sample_mapping_fields }", path=FN,
              source=f"{WF}:126", op="filter", category="reporting",
              notes="Filters on a value, not on the items: passes everything or nothing.")
p_mqc = P("MULTIQC_MAPPINGS_CONFIG", module="modules/local/multiqc_mappings_config/main.nf", flows=MAPPINGS, category="reporting")
o_smap = N("out.sample_mappings", "output", "*config.yml", path=FN, source=f"{WF}:145", flows=MAPPINGS, category="reporting")

# Versions
topic = N("topic.versions", "source", "channel.topic('versions')", path=FN, source=f"{WF}:133", category="versions", lane="versions",
          notes="Every process emits its versions to this topic. The preview DAG does not draw that wiring: each emit is a loose point, and the topic is a separate source point.")
v_tolist = N("FETCHNGS/toList@versions", "operator", "toList (inside softwareVersionsToYAML)", path=FN, source=f"{WF}:132-134",
             op="toList", category="versions", lane="versions")
v_map = N("FETCHNGS/map@versions_yaml", "operator", "map (inside softwareVersionsToYAML)", path=FN, source=f"{WF}:132-134",
          op="map", category="versions", lane="versions")
v_cf = N("FETCHNGS/collectFile@versions", "operator", "collectFile(storeDir: outdir/pipeline_info, name: nf_core_fetchngs_software_versions.yml)",
         path=FN, source=f"{WF}:135-140", op="collectFile", category="versions", lane="versions")
o_vers = N("out.versions", "output", "pipeline_info/nf_core_fetchngs_software_versions.yml", path=FN, source=f"{WF}:147",
           category="versions", lane="versions")

# ---- edges -----------------------------------------------------------------
PER_ID = dict(card="queue", per="input id")
PER_RUN = dict(card="queue", per="run accession")

E(ids_src, ids_u, contents=C(card="queue", per="input id", meta=None,
  text="one per row of --input", shape=None))
edges[-1]["contents"]["from"]["shape"] = "unknown"
E(ids_u, p_ids, "ids", dot="ids", contents=C("id", meta=None, src="declared", **PER_ID))
E(fields, p_ids, "fields", dot="fields", contents=C("fields", "value", meta=None, src="declared",
  files="none: a comma-separated string"))
E(p_ids, p_ftp_tsv, "tsv", contents=C("path", meta=None, files="*.tsv runinfo, one per input id", src="declared", **PER_ID))
E(p_ftp_tsv, o_filter, "tsv", contents=C("path", meta=None, files="*.tsv with FTP and Aspera links, one per input id", src="declared", **PER_ID))
E(o_filter, o_split, contents=C("path", meta=None, files="as above, empty files dropped", src="inferred", **PER_ID))
E(o_split, o_se, contents=C("meta", meta=run_meta(), card="queue", per="run accession",
  text="one item per row: an input id can expand to many runs"))
E(o_se, o_uniq, contents=C("meta", meta=run_meta(text="single_end converted from string to boolean. " + META_TEXT), **PER_RUN))
E(o_uniq, o_branch, "ch_sra_metadata", dot="ch_sra_metadata", when=DL,
  contents=C("meta", meta=run_meta(), src="inferred", **PER_RUN))

# branch outputs, each with the shape its return statement gives
E(o_branch, p_ftp, "ch_sra_reads.ftp", operator="branch: ftp", when=DL, flows=FLOW["ftp"],
  contents=C("[meta, [fastq_1, fastq_2]]", meta=run_meta(), files="none yet: FTP URLs as strings", **PER_RUN))
E(o_branch, o_collect, "ch_sra_ids", dot="ch_sra_ids", operator="branch: sratools", when=DL, flows=FLOW["sratools"],
  contents=C("[meta, run_accession]", meta=run_meta(), **PER_RUN))
E(o_branch, p_pre, "ch_sra_ids", dot="ch_sra_ids", operator="branch: sratools", when=DL, flows=FLOW["sratools"],
  contents=C("[meta, run_accession]", meta=run_meta(), **PER_RUN))
E(o_branch, p_asp, "ch_sra_reads.aspera", operator="branch: aspera", when=DL, flows=FLOW["aspera"],
  contents=C("[meta, [aspera_link_1, aspera_link_2]]", meta=run_meta(), files="none yet: Aspera URLs as strings, at most two (take(2))", **PER_RUN))
E(o_branch, p_fdl, "ch_sra_reads.fastqdl", operator="branch: fastqdl", when=DL, flows=FLOW["fastq-dl"],
  contents=C("[meta, run_accession]", meta=run_meta(), **PER_RUN))

# FTP
E(p_ftp, o_mix1, "fastq", when=DL, flows=FLOW["ftp"],
  contents=C("[meta, *fastq.gz]", meta=run_meta(), files="FastQ, one or two per run", src="declared", **PER_RUN))
E(p_ftp, o_ftp_md5, "md5", when=DL, flows=FLOW["ftp"], contents=C("[meta, *md5]", meta=run_meta(), src="declared", **PER_RUN))
# sratools
E(o_collect, p_ncbi, "ids", when=DL, flows=FLOW["sratools"],
  contents=C("[meta, run_accession, meta, run_accession, ...]", "value", meta=None,
             text="collect flattens the tuples into one list; the module only uses it as a trigger"))
E(p_ncbi, p_pre, "ch_ncbi_settings", dot="ch_ncbi_settings", when=DL, flows=FLOW["sratools"],
  contents=C("path", "value", meta=None, files="*.mkfg NCBI settings", src="declared", cardinality="annotated"))
E(p_ncbi, p_fqd, "ch_ncbi_settings", dot="ch_ncbi_settings", when=DL, flows=FLOW["sratools"],
  contents=C("path", "value", meta=None, files="*.mkfg NCBI settings", src="declared", cardinality="annotated"))
E(dbgap, p_pre, "certificate", dot="certificate", when=DL,
  contents=C("path", "value", meta=None, files="the dbGaP key file, or [] when --dbgap_key is unset", src="declared"))
E(dbgap, p_fqd, "certificate", dot="certificate", when=DL,
  contents=C("path", "value", meta=None, files="the dbGaP key file, or [] when --dbgap_key is unset", src="declared"))
E(p_pre, p_fqd, "sra", when=DL, flows=FLOW["sratools"],
  contents=C("[meta, sra]", meta=run_meta(), files="SRA directory named after the accession", src="declared", **PER_RUN))
E(p_fqd, o_mix1, "reads", dot="reads", when=DL, flows=FLOW["sratools"],
  contents=C("[meta, *.fastq.gz]", meta=run_meta(), files="FastQ, one or two per run", src="declared", **PER_RUN))
# Aspera
E(user, p_asp, "user", dot="user", when=DL, contents=C("user", "value", meta=None, src="declared", files="none: the string 'era-fasp'"))
E(p_asp, o_mix2, "fastq", when=DL, flows=FLOW["aspera"],
  contents=C("[meta, *fastq.gz]", meta=run_meta(), files="FastQ, one or two per run", src="declared", **PER_RUN))
E(p_asp, o_asp_md5, "md5", when=DL, flows=FLOW["aspera"], contents=C("[meta, *md5]", meta=run_meta(), src="declared", **PER_RUN))
# fastq-dl
E(p_fdl, o_mix3, "fastq", when=DL, flows=FLOW["fastq-dl"],
  contents=C("[meta, *.fastq.gz]", meta=run_meta(), files="FastQ, one or two per run", src="declared", **PER_RUN))
E(p_fdl, o_fdl_ri, "runinfo", when=DL, flows=FLOW["fastq-dl"], contents=C("[meta, *-run-info.tsv]", meta=run_meta(), src="declared", **PER_RUN))
E(p_fdl, o_fdl_rm, "runmergers", when=DL, flows=FLOW["fastq-dl"],
  contents=C("[meta, *-run-mergers.tsv]", meta=run_meta(), src="declared", card="queue", per="run accession", text="optional: absent for most runs"))
# merge
MIXED = C("[meta, fastq]", meta=run_meta(), src="inferred", files="FastQ from whichever route each run took; a single path or a list", **PER_RUN)
E(o_mix1, o_mix2, when=DL, contents=MIXED)
E(o_mix2, o_mix3, when=DL, contents=MIXED)
E(o_mix3, o_paths, when=DL, contents=MIXED)
PUBLISHED = C("meta", meta=run_meta(text="fastq_1 and fastq_2 rewritten to the published paths under --outdir; the files themselves are no longer in the channel. " + META_TEXT), **PER_RUN)
E(o_paths, c_map1, "sra_metadata", dot="sra_metadata", when=DL, contents=PUBLISHED)
E(o_paths, c_map3, "sra_metadata", dot="sra_metadata", when=DL, contents=PUBLISHED)
SKIPPED = C("meta", meta=run_meta(text="as read from the runinfo: fastq_1 and fastq_2 are FTP URLs, nothing was downloaded. " + META_TEXT), **PER_RUN)
E(o_uniq, c_map1, "sra_metadata", dot="sra_metadata", when=SKIP, contents=SKIPPED,
  notes="Only with --skip_fastq_download: ch_sra_metadata is not reassigned, so the samplesheet is built from the runinfo directly.")
E(o_uniq, c_map3, "sra_metadata", dot="sra_metadata", when=SKIP, contents=SKIPPED)

# samplesheet and mappings
ROW = C("string", meta=None, files="none: one CSV header line and one value line", **PER_RUN)
E(c_map1, c_cf1, contents=ROW)
E(c_cf1, c_map2, contents=C("path", "single", meta=None, files="tmp_samplesheet.csv"))
E(c_map2, c_cf2, contents=C("string", "single", meta=None, files="none: the CSV text"))
E(c_cf2, o_sheet, "samplesheet", dot="samplesheet", contents=C("path", "single", meta=None, files="samplesheet.csv, published"))
E(c_map3, c_cf3, contents=ROW)
E(c_cf3, c_map4, contents=C("path", "single", meta=None, files="tmp_id_mappings.csv"))
E(c_map4, c_cf4, contents=C("string", "single", meta=None, files="none: the CSV text"))
E(c_cf4, o_mfilter, "mappings", dot="mappings", contents=C("path", "single", meta=None, files="id_mappings.csv, published"))
E(o_mfilter, p_mqc, "csv", flows=MAPPINGS, contents=C("path", "single", meta=None, files="id_mappings.csv", src="declared", cardinality="annotated"))
E(p_mqc, o_smap, "sample_mappings", dot="sample_mappings", flows=MAPPINGS,
  contents=C("path", "single", meta=None, files="*config.yml MultiQC sample-name mappings", src="declared", cardinality="annotated"))

# versions: one edge per versions emit. DOT draws each as a loose output point.
for proc, n in [(p_ids, 1), (p_ftp_tsv, 1), (p_ftp, 1), (p_ncbi, 1), (p_pre, 2), (p_fqd, 2), (p_asp, 1), (p_fdl, 1), (p_mqc, 1)]:
    pn = next(x for x in nodes if x["id"] == proc)
    for i in range(n):
        E(proc, topic, f"versions{'' if n == 1 else i + 1}", when=pn.get("when"), flows=pn.get("flows_when"),
          contents=VERSIONS, lane="versions")
E(topic, v_tolist, lane="versions", contents=C("[process, tool, version]", "queue", "task", meta=None))
E(v_tolist, v_map, lane="versions", contents=C("[[process, tool, version], ...]", "single", meta=None))
E(v_map, v_cf, lane="versions", contents=C("string", "single", meta=None, files="none: YAML text"))
E(v_cf, o_vers, "versions", dot="versions", lane="versions", contents=C("path", "single", meta=None, files="nf_core_fetchngs_software_versions.yml, published"))

# ---- runs ------------------------------------------------------------------
RUNS = [
    ("baseline", "", "ftp", False),
    ("dl_aspera", "--download_method aspera", "aspera", False),
    ("dl_fastqdl", "--download_method fastq-dl", "fastq-dl", False),
    ("dl_sratools", "--download_method sratools", "sratools", False),
    ("dl_sratools_dbgap", "--download_method sratools --dbgap_key dummy.ngc", "sratools", False),
    ("dl_ftp_dbgap", "--dbgap_key dummy.ngc", "ftp", False),
    ("nfcore_rnaseq", "--nf_core_pipeline rnaseq", "ftp", False),
    ("skip_download", "--skip_fastq_download", "ftp", True),
]
runs = [{"id": r, "args": a, "status": "ok",
         "settings": {"download_method": m, "skip_fastq_download": s, "sample_mapping_fields": "present"},
         "dag": f"working_docs/fetchngs-preview/{r}.dot", "date": "2026-10-10"} for r, a, m, s in RUNS]

for x in nodes + edges:
    x["observed_in"] = [r["id"] for r in runs if holds(x.get("when"), r["settings"], DIMS) is not False]

# ---- assemble --------------------------------------------------------------
dot_labels = {e["id"]: e.pop("_dot") for e in edges}

model = {
    "schema_version": "0.1",
    "pipeline": {"name": "nf-core/fetchngs", "version": "1.13.0", "revision": "955c892d80927cee633765e6e390f9cc6b7235c9",
                 "repository": "https://github.com/nf-core/fetchngs", "nextflow_version": "26.04.6",
                 "prefix": ["NFCORE_FETCHNGS", "FETCHNGS"]},
    "generated": {"tool": "process-flow fixtures/fetchngs_spec.py (hand-modelled)", "date": "2026-10-10",
                  "sources": ["main.nf", WF, CSVF, SRAF, UTIL, "modules/*/main.nf", "working_docs/fetchngs-preview/*.dot"]},
    "dimensions": dimensions,
    "routes": {"dimension": "download_method",
               "colours": {"aspera": "#7048e8", "fastq-dl": "#f08c00", "ftp": "#1c7ed6", "sratools": "#c2255c"}},
    "palette": {"shared": "#495057", "samplesheet": "#0ca678", "reporting": "#868e96", "versions": "#adb5bd", "input": "#9aa3ad"},
    "lanes": [
        {"id": "main", "label": "data flow", "mode": "expanded"},
        {"id": "versions", "label": "versions via channel.topic('versions')", "hub": topic, "mode": "hidden"},
    ],
    "groups": [
        {"path": PI, "label": "PIPELINE_INITIALISATION", "source": UTIL},
        {"path": SRA, "label": "sra-tools download", "source": SRAF},
        {"path": CSV, "label": "samplesheet", "source": CSVF,
         "notes": "A subworkflow with no processes: the preview DAG gives no sign it exists."},
    ],
    "runs": runs,
    "nodes": nodes,
    "edges": edges,
}
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(model, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(nodes)} nodes, {len(edges)} edges, {len(runs)} runs")

# ---- checks ----------------------------------------------------------------
failed = False
try:
    import jsonschema
    schema = json.load(open(os.path.join(ROOT, "schema", "channels.schema.json"), encoding="utf-8"))
    errs = list(jsonschema.Draft202012Validator(schema).iter_errors(model))
    print(f"schema: {'ok' if not errs else f'{len(errs)} errors'}")
    for e in errs[:10]: print("  ", e.json_path, e.message[:150])
    failed |= bool(errs)
except ImportError:
    print("schema: skipped (pip install jsonschema)")

by_id = {n["id"]: n for n in nodes}
def sig(n):
    if n["kind"] == "process": return ":".join(n["path"])
    t = (n.get("operator") or {}).get("type")
    return f"op:{t}" if t else "point"

for r in runs:
    s = r["settings"]
    live_n = [n for n in nodes if holds(n.get("when"), s, DIMS) is not False]
    live_e = [e for e in edges if holds(e.get("when"), s, DIMS) is not False]
    predicted = {
        "processes": collections.Counter(sig(n) for n in live_n if n["kind"] == "process"),
        "operators": collections.Counter(n["operator"]["type"] for n in live_n if (n.get("operator") or {}).get("type")),
        "edges": collections.Counter((sig(by_id[e["from"]]), sig(by_id[e["to"]]), dot_labels[e["id"]]) for e in live_e),
    }
    actual = dot.summary(os.path.join(PREVIEW, f"{r['id']}.dot"))
    diffs = [k for k in predicted if predicted[k] != actual[k]]
    print(f"{r['id']:<18} {'ok' if not diffs else 'DIFFERS: ' + ', '.join(diffs)}"
          f"  ({sum(predicted['processes'].values())} processes, {sum(predicted['operators'].values())} operators, {sum(predicted['edges'].values())} edges)")
    for k in diffs:
        print(f"   {k}: model only {dict(predicted[k] - actual[k])}; DAG only {dict(actual[k] - predicted[k])}")
    failed |= bool(diffs)

from predicates import state
print("\ndisplay state of each process, by download_method (downloads on, mapping fields set):")
procs = [n for n in nodes if n["kind"] == "process"]
print(f"   {'':<30}" + "".join(f"{m:<10}" for m in DIMS["download_method"]["values"]) + "skip")
for n in procs:
    row = [state(n, {"download_method": m, "skip_fastq_download": False, "sample_mapping_fields": "present"}, DIMS)
           for m in DIMS["download_method"]["values"]]
    row.append(state(n, {"download_method": None, "skip_fastq_download": True, "sample_mapping_fields": "present"}, DIMS))
    print(f"   {n['label']:<30}" + "".join(f"{x:<10}" for x in row))

cov = collections.Counter()
for e in edges:
    fr = e.get("contents", {}).get("from", {})
    for k in ("shape", "meta", "cardinality", "files"):
        cov[(k, fr.get(k, "absent"))] += 1
print("contents provenance:", ", ".join(f"{k} {v}={n}" for (k, v), n in sorted(cov.items())))

sys.exit(1 if failed else 0)
