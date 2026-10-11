// =============================================================================
// process-flow User Guide generator
// -----------------------------------------------------------------------------
// Builds ../process-flow_User_Guide.docx from the content defined in this file.
// The Word document is generated, not hand-edited: edit the `children` array
// below and re-run to regenerate.
//
//   cd docs
//   npm install          # one-time, installs docx and the SVG renderer
//   npm run build        # or: node build_user_guide.js
//
// The logo is rendered from ../assets/process-flow_logo.svg, the same file the
// viewer shows, into ../assets/process-flow_logo.png; the version is read from
// ../tools/version.py. The .docx is written to the repository root.
// =============================================================================

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, TableOfContents, HeadingLevel,
  BorderStyle, WidthType, ShadingType, PageNumber, PageBreak, TabStopType,
  TabStopPosition
} = require('docx');
const { Resvg } = require('@resvg/resvg-js');

const REPO_ROOT   = path.join(__dirname, '..');
const OUTPUT_DOCX = path.join(REPO_ROOT, 'process-flow_User_Guide.docx');
const LOGO_SVG    = path.join(REPO_ROOT, 'assets', 'process-flow_logo.svg');
const LOGO_PNG    = path.join(REPO_ROOT, 'assets', 'process-flow_logo.png');

// The logo, rendered from the SVG the viewer uses, so the two cannot drift.
// Twice the size it is shown at, for print.
const logoBuffer = new Resvg(fs.readFileSync(LOGO_SVG), {
  fitTo: { mode: 'width', value: 1200 },
  font: { loadSystemFonts: true, defaultFontFamily: 'Arial' },
  background: 'rgba(255,255,255,0)',
}).render().asPng();
fs.writeFileSync(LOGO_PNG, logoBuffer);

// The version is read from tools/version.py, the one place it is
// authoritative (it is also stamped into every model process-flow publishes).
const VERSION = (fs.readFileSync(path.join(REPO_ROOT, 'tools', 'version.py'), 'utf8')
  .match(/^VERSION\s*=\s*"([^"]+)"/m) || [])[1];
if (!VERSION) throw new Error("could not read VERSION from tools/version.py");

const CONTENT_W = 9360;
// the logo's own colours: the trunk blue, and the first route line
const BLUE = "1F4E79", ACCENT = "C2255C";

// ---- helpers --------------------------------------------------------------
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });

function P(text, opts = {}) {
  const runs = Array.isArray(text)
    ? text
    : [new TextRun({ text, bold: !!opts.bold, italics: !!opts.italics })];
  return new Paragraph({ children: runs, spacing: { after: 120 }, ...opts.p });
}
const BOLD = (t) => new TextRun({ text: t, bold: true });
const PLAIN = (t) => new TextRun({ text: t });
const CODE = (t) => new TextRun({ text: t, font: "Consolas", size: 20 });

function bullet(text) {
  const runs = Array.isArray(text) ? text : [new TextRun(text)];
  return new Paragraph({ numbering: { reference: "bullets", level: 0 },
    children: runs, spacing: { after: 60 } });
}

// codeBlock() returns an array of paragraphs and must be spread into children
// (pushed as one element, docx writes invalid XML and Word refuses the file).
function codeBlock(lines) {
  return lines.map((ln, i) =>
    new Paragraph({
      shading: { type: ShadingType.CLEAR, fill: "F4F4F4" },
      spacing: { before: i === 0 ? 60 : 0, after: i === lines.length - 1 ? 140 : 0 },
      indent: { left: 120 },
      children: [new TextRun({ text: ln || " ", font: "Consolas", size: 19 })],
    }));
}

function note(text) {
  const runs = Array.isArray(text) ? text : [new TextRun(text)];
  return new Paragraph({
    shading: { type: ShadingType.CLEAR, fill: "FFF4CE" },
    border: { left: { style: BorderStyle.SINGLE, size: 18, color: "E0A800", space: 6 } },
    indent: { left: 160 }, spacing: { before: 80, after: 140 },
    children: [BOLD("Note  "), ...runs],
  });
}

function cell(text, w, { head = false } = {}) {
  const runs = (Array.isArray(text) ? text : [text]).map(seg =>
    typeof seg === "string"
      ? new TextRun({ text: seg, bold: head, color: head ? "FFFFFF" : "000000", size: 19 })
      : seg);
  return new TableCell({
    width: { size: w, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: head ? BLUE : "FFFFFF" },
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    children: [new Paragraph({ children: runs })],
  });
}

function table(widths, rows) {
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({
      children: r.map((c, ci) => cell(c, widths[ci], { head: ri === 0 })),
      tableHeader: ri === 0,
    })),
  });
}
const spacer = () => new Paragraph({ spacing: { after: 80 }, children: [] });
const PF = "/path/to/process-flow";

// ---------------------------------------------------------------------------
const children = [];

// Title page
children.push(
  new Paragraph({ spacing: { before: 2300, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new ImageRun({ type: "png", data: logoBuffer,
      transformation: { width: 480, height: 102 } })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 160, after: 0 },
    children: [new TextRun({ text: "See what a Nextflow pipeline's channels carry", size: 32, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 480, after: 0 },
    children: [new TextRun({ text: "User Guide", size: 30, bold: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 0 },
    children: [new TextRun({ text: "Version " + VERSION, size: 24, color: "595959" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2200, after: 0 },
    children: [new TextRun({ text: "For any Nextflow DSL2 pipeline; tested on nf-core/rnaseq, nf-core/sarek and nf-core/fetchngs",
      italics: true, size: 22, color: "595959" })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// TOC
children.push(
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Contents")] }),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),
);

// 1. About
children.push(H1("1. About process-flow"));
children.push(P("A Nextflow pipeline is processes joined by channels, and most of its bugs live in the channels: a tuple of the wrong shape, a meta map missing a key, a join that silently drops samples, a collect that should have been a queue. nextflow run -with-dag draws the graph, but nothing on its edges: it shows that two processes are joined, not what passed between them."));
children.push(P("process-flow adds what the DAG leaves out. Run a pipeline's test once, and it writes a single HTML page beside the MultiQC report showing every process, every operator and every channel between them, with what actually went through each one in that run, and the conditions under which each element exists, so the page can be filtered to any route the pipeline can take."));
children.push(H2("Two ways to use it"));
children.push(table([2300, 3530, 3530], [
  ["", "The Explorer", "The Analyser"],
  ["For", "Anyone who wants to see and understand a pipeline", "Pipeline authors who want exact conditions for every route, published with a release"],
  ["You do", "One command: process-flow run, with the pipeline's usual arguments", "A matrix of preview runs, planned for you, in a few batches"],
  ["Cost", "One test run (nf-core/rnaseq: about 10 to 20 minutes)", "Hundreds of previews (nf-core/rnaseq: 357, about an hour and a half, six at a time)"],
  ["Conditions", "From a published model if the pipeline ships one; otherwise read from the code", "Proven against every preview"],
  ["Contents", "What the run actually carried", "Declared shapes and ports; a real run can be laid over it"],
]));
children.push(spacer());
children.push(P([BOLD("Most people only need the Explorer. "), PLAIN("Sections 3 to 6 cover it. Section 7 is for pipeline authors.")]));
children.push(H2("What the page shows"));
children.push(bullet([BOLD("The whole graph: "), PLAIN("every process and operator, nested in its subworkflows (collapsible), with the version-and-MultiQC plumbing folded so the data flow reads clearly.")]));
children.push(bullet([BOLD("What the run carried: "), PLAIN("on every channel into or out of a process, the meta keys, whether it was a queue of one item per sample, a value given to every task or a collection, and real items, such as [[id:WT_REP1, strandedness:reverse, ...], [WT_REP1_1.fastq.gz, WT_REP1_2.fastq.gz]]. On channels between operators, the files that passed and where they came from and went.")]));
children.push(bullet([BOLD("What ran: "), PLAIN("tasks per process, and processes that were wired into the run but received nothing.")]));
children.push(bullet([BOLD("When each element exists: "), PLAIN("a filter for every parameter the code tests, and for every element its condition in words, such as --aligner = star_salmon | star_rsem; no --skip_alignment. Pick a setting and the page shows what that run would wire together.")]));
children.push(bullet([BOLD("Routes as a metro map: "), PLAIN("the parameter that splits the most processes (an aligner, usually) colours the graph, one line per value.")]));
children.push(bullet([BOLD("One file: "), PLAIN("the page needs no server and no network. Open it, send it, attach it to an issue.")]));

// 2. Requirements
children.push(H1("2. Requirements & installation"));
children.push(bullet([BOLD("Linux or WSL. "), PLAIN("process-flow runs Nextflow, so it runs where Nextflow does. On Windows, use WSL2 and keep run folders on the Linux filesystem.")]));
children.push(bullet([BOLD("Nextflow 25.04 or later "), PLAIN("(for data lineage, which records what each task received and produced). Tested on 26.04. Nextflow needs Java 17 or later.")]));
children.push(bullet([BOLD("Python 3.8 or later. "), PLAIN("process-flow uses only the standard library; nothing to pip install. jsonschema is optional: with it, every model is checked against the schema before a page is built.")]));
children.push(bullet([BOLD("Whatever the pipeline needs to run "), PLAIN("(Docker, Singularity/Apptainer or Conda), chosen with its usual -profile.")]));
children.push(P([BOLD("Install. "), PLAIN("There is nothing to build. Download or clone the repository anywhere, and run bin/process-flow from it:")]));
children.push(...codeBlock([
  "git clone https://github.com/nicholas-owen/process-flow.git",
  "process-flow/bin/process-flow --help",
]));
children.push(P("To call it as process-flow from anywhere, put the bin folder on your PATH, or run it as bash /path/to/process-flow/bin/process-flow. The pipeline itself needs no change, and is never modified."));

// 3. Quick start
children.push(H1("3. Quick start"));
children.push(P("Make a folder for the run, and run the pipeline's test through process-flow. Everything after run goes to nextflow run unchanged:"));
children.push(...codeBlock([
  "mkdir -p ~/runs/rnaseq && cd ~/runs/rnaseq",
  `${PF}/bin/process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results`,
]));
children.push(P([PLAIN("When the run ends, open "), CODE("results/pipeline_info/channels.html"), PLAIN(" in a browser. From Windows, a WSL folder is reachable as \\\\wsl$\\Ubuntu\\home\\<you>\\runs\\rnaseq\\results\\pipeline_info\\channels.html.")]));
children.push(P([BOLD("Check the config first. "), PLAIN("A release whose own configuration does not parse fails before anything runs. nextflow config pulls the release and parses it in seconds; if it prints an error, the run would have failed too (section 8):")]));
children.push(...codeBlock([
  "nextflow config nf-core/sarek -r 3.10.0 -profile test,docker | tail -5",
]));
children.push(P([BOLD("Small machines. "), PLAIN("nf-core test profiles ask for up to 4 CPUs and 15 GB. If yours has less, cap it in a config and pass it with -c. It changes how much a task may ask for, never which processes run or how they are joined:")]));
children.push(...codeBlock([
  "echo 'process.resourceLimits = [cpus: 4, memory: 12.GB, time: 6.h]' > limits.config",
  `${PF}/bin/process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results -c limits.config`,
]));
children.push(note("If the run fails, process-flow builds nothing. Fix the cause and rerun the same command with -resume: tasks that already finished are taken from Nextflow's cache, and process-flow counts them."));

// 4. How a run becomes a page
children.push(H1("4. How a run becomes a page"));
children.push(H2("4.1 process-flow run"));
children.push(P("run adds one config file to the command, .process-flow/capture.config in the launch folder, and changes nothing else:"));
children.push(...codeBlock([
  "lineage.enabled = true",
  "dag { enabled = true; overwrite = true; file = '<outdir>/pipeline_info/process-flow/dag.dot' }",
]));
children.push(P("Data lineage makes Nextflow record every task in .lineage in the launch folder: each input and output as it was, meta maps included, and for each file the task that made it. The DAG is the graph of the run. When Nextflow exits successfully, run goes on to explore."));
children.push(H2("4.2 process-flow explore"));
children.push(P("explore builds the page from a run already made. It reads the latest run in .lineage (and the tasks a -resume took from the cache), and from that run's record: where Nextflow put the pipeline's source, the output folder, the commit, and the params. nf-core pipelines also write the params as they used them, after filling genome attributes in, to pipeline_info/params_*.json; explore reads those when they are there. Then:"));
children.push(bullet([BOLD("The model. "), PLAIN("If the pipeline ships a published model for its release (assets/process-flow/channels.json), explore uses it. Otherwise it builds one from the run's DAG: modules, ports and declared tuple shapes from the module files, and each element's condition read from the code (section 6).")]));
children.push(bullet([BOLD("The run, laid over it. "), PLAIN("Meta keys, items and provenance on every channel at a process, the files on channels between operators, tasks per process, and a check of the run against the model.")]));
children.push(bullet([BOLD("The page. "), PLAIN("channels.html, with the model beside it as channels.json.")]));
children.push(P("Run explore yourself to rebuild a page (after updating process-flow, say) without running the pipeline again, or to build one from a run made without process-flow:"));
children.push(...codeBlock([
  "cd ~/runs/rnaseq",
  `${PF}/bin/process-flow explore`,
  "",
  "# a run made with lineage.enabled = true and -with-dag dag.dot",
  `${PF}/bin/process-flow explore --run-dir . --dag dag.dot`,
]));
children.push(table([2400, 6960], [
  ["explore option", "Default and purpose"],
  ["--run-dir DIR", "Where the run was launched, holding .lineage. Default: the current folder"],
  ["--outdir DIR", "The run's --outdir. Default: read from the run"],
  ["--source DIR", "The pipeline's source. Default: where Nextflow pulled it"],
  ["--model FILE", "A published model to use in place of the pipeline's own (examples/published/ has two)"],
  ["--dag FILE", "The run's DAG. Default: <outdir>/pipeline_info/process-flow/dag.dot"],
  ["-o, --out FILE", "The page. Default: <outdir>/pipeline_info/channels.html"],
  ["--logo FILE", "The pipeline's own logo, shown in the page header"],
]));
children.push(spacer());
children.push(H2("4.3 What it writes"));
children.push(table([3900, 5460], [
  ["File", "What"],
  ["<outdir>/pipeline_info/channels.html", "The page"],
  ["<outdir>/pipeline_info/channels.json", "The channel model behind it (schema 0.1), with the run laid over it"],
  ["<outdir>/pipeline_info/process-flow/dag.dot", "The run's DAG"],
  [".lineage/ (launch folder)", "Nextflow's lineage store: every task's inputs and outputs. Kept by Nextflow, a few MB"],
  [".process-flow/capture.config (launch folder)", "The config run added"],
]));
children.push(spacer());

// 5. Reading the page
children.push(H1("5. Reading the page"));
children.push(P("The page has three parts: the filters on the left, the graph, and a detail panel for whatever you click. A first pass that works: press Show this run's settings, then click a channel going into a process you care about."));
children.push(H2("5.1 The This run box"));
children.push(P("At the top of the filters: the run's name and release, its tasks and processes, the check against the model, the processes that were wired but received nothing (each a link to it in the graph), and a button that sets every filter to the run's own settings. With a published model, the check names any difference between the run and the model, and the setting behind it (section 6.3)."));
children.push(H2("5.2 Filters"));
children.push(bullet([BOLD("The route "), PLAIN("comes first: tick values to light their lines. None ticked colours every element by the routes that use it.")]));
children.push(bullet([BOLD("Choice parameters "), PLAIN("(an enum, such as --trimmer) follow, ordered by how many processes each one decides. That count is the small grey badge on every filter.")]));
children.push(bullet([BOLD("On/off and set/unset options "), PLAIN("are grouped by the section of the pipeline's own schema they belong to (Process skipping options, Reference genome options, ...), each group folding, the busiest open. A comma-separated list such as sarek's --tools becomes one switch per value. A search box finds an option by name.")]));
children.push(bullet([BOLD("Each section counts the options set away from the pipeline's default, "), PLAIN("so after Show this run's settings you can see at a glance where the test profile differs from a default run.")]));
children.push(bullet([BOLD("any "), PLAIN("leaves a setting open: an element is lit if it exists under some value of it.")]));
children.push(H2("5.3 The graph"));
children.push(table([2600, 6760], [
  ["You see", "It means"],
  ["A lit node or channel", "It exists under the settings chosen"],
  ["Dimmed", "It does not exist under those settings"],
  ["Dashed", "It exists but may receive nothing, depending on the data (starved)"],
  ["Coloured lines", "The route values that use it; shared stretches in more than one colour"],
  ["A dashed box", "A subworkflow; click its name to collapse it to one node"],
  ["A folded hub", "Plumbing (software versions, files collected for MultiQC) folded onto the point where it leaves; unfold it under Lanes"],
]));
children.push(spacer());
children.push(H2("5.4 The detail panel"));
children.push(table([2200, 7160], [
  ["Row", "What it says"],
  ["shape", "The tuple as a map closure would see it, such as [meta, reads], from the module's declaration"],
  ["meta", "The meta map's keys in this run; keys differ between items is said when they do (a key added for some samples only)"],
  ["cardinality", "queue (one item per sample, per meta.id), value (the same item given to every task), single, or collected (one item holding many files)"],
  ["files", "On a channel between operators: the files that passed and where they came from and went"],
  ["port", "Which output of the producer and which input of the consumer, such as emit bam -> input 1"],
  ["exists when", "Its condition, in words. always if it exists under every setting"],
  ["now", "Its state under the settings chosen"],
  ["this run", "For a process: how many tasks it ran, or that it was wired and received nothing"],
  ["Worked example", "Real items from the run, one per sample; show all to see every one"],
]));
children.push(spacer());
children.push(P("Every value carries a small label saying where it came from:"));
children.push(table([1700, 7660], [
  ["Label", "Where the value came from"],
  ["harvested", "The run itself, from Nextflow's lineage"],
  ["declared", "The module's input and output declarations"],
  ["inferred", "Carried through an operator that does not change shape (filter, first, mix of like channels)"],
  ["preview", "Proven over a matrix of preview runs (a published model)"],
  ["source", "Read from the pipeline's code (section 6). Less sure than preview"],
  ["unknown", "Nobody knows yet. An unknown is a finding, not a gap"],
]));
children.push(spacer());

// 6. Where the conditions come from
children.push(H1("6. Where the conditions come from"));
children.push(H2("6.1 A published model"));
children.push(P("If the pipeline's authors ran the Analyser (section 7) and committed the result as assets/process-flow/channels.json, the page uses it. Its conditions are proven: every one agrees with every preview run behind it, hundreds of them, and they cover the routes your run did not take. The page footer says how the model was proven: how many previews, which arguments were held the same in all of them, and which parameters were not varied."));
children.push(H2("6.2 Read from the code"));
children.push(P("Otherwise process-flow reads the conditions from the pipeline itself. A process exists when its call runs: its call in the workflow that holds it sits inside zero or more if blocks, as does that workflow's call in its own, and so on to the top. Rather than turning those conditions into formulas, process-flow interprets the code once for each setting of the parameters the conditions read:"));
children.push(bullet([PLAIN("params.x is the setting being tried, or the run's own value;")]));
children.push(bullet([PLAIN("a workflow's input is followed back to the argument its caller passed (params.skip_fastqc || params.skip_qc, two levels up);")]));
children.push(bullet([PLAIN("a local variable replays its assignments and list appends, each under its own ifs, so 'sortmerna' in prepare_tool_indices is answered the way the code builds the list;")]));
children.push(bullet([PLAIN("==, in, !, &&, ||, ?:, contains, startsWith and simple one-line closures work; anything else (a helper function that edits a list, a value read from a file) is unknown, and says so.")]));
children.push(P("Operators and channels are then placed: an operator is the statement of that type naming its neighbours, and exists when that statement runs; a channel exists when both its ends do. Scored against the Analyser's proven models:"));
children.push(table([4560, 1600, 1600, 1600], [
  ["Read from the code, against a proven model", "Exact", "Wrong", "Undecided"],
  ["nf-core/fetchngs 1.13.0, everything (117)", "117", "0", "0"],
  ["nf-core/rnaseq 3.27.0, processes (101)", "94", "0", "7"],
  ["nf-core/rnaseq 3.27.0, everything (2,289)", "1,902", "281", "106"],
]));
children.push(spacer());
children.push(P("So: processes are right wherever the code is plain, and operators and channels are mostly right. What is left wrong is mostly folded plumbing, where several look-alike operators in different places cannot be told apart. An element the run shows to exist, but whose condition says it should not, is marked unknown rather than shown wrong."));
children.push(H2("6.3 The check against a published model"));
children.push(P("When the page uses a published model, the run is checked against it: the processes and channels the model expects under the run's settings, against those the run wired and ran. Where they differ, process-flow looks for an argument the model's previews held fixed that this run changed, and names it. nf-core/rnaseq's published model, for example, was built with --transcript_fasta unset (the test profile could not be previewed otherwise); the real test profile sets it, and the This run box says so: 22 differences, all explained by --transcript_fasta. A difference nothing explains is shown in bold: the model is stale or wrong for this run."));
children.push(H2("6.4 What no condition can say"));
children.push(P("Some pipelines decide per sample, inside the data: sarek wires every aligner in every run and sends each sample to the one chosen with a channel filter; fetchngs chooses a download method for each sample in a branch. No setting of the parameters decides those, so those processes exist under every setting, and the run shows which received data (wired but received nothing). Two calls of one process in branches that never meet also look like one process."));

// 7. The Analyser
children.push(H1("7. The Analyser: for pipeline authors"));
children.push(P("The Analyser proves every element's condition, over every route, by previewing the pipeline under many settings. A preview (nextflow run -preview -with-dag) builds the graph a run would build and stops: no containers, no data. process-flow plans which settings to preview, lines the resulting graphs up so the same operator is recognised in each, and infers for every node and channel the condition under which it exists. You publish the result with your pipeline, and every user's page then uses it."));
children.push(P([BOLD("Cost. "), PLAIN("nf-core/rnaseq took 357 previews, about a minute each, six at a time: an hour and a half of machine time, in five batches. fetchngs took 14. You run batches and the planner says when nothing is left.")]));
children.push(H2("7.1 The steps"));
children.push(P("In a working folder on the Linux filesystem, with the pipeline's source for the release in src/ (git clone --branch <release>):"));
children.push(...codeBlock([
  `PF=${PF}`,
  "",
  "# 1. which params may change the graph (edit include: true/false in proposal.json)",
  "python3 $PF/tools/propose.py src/nextflow_schema.json --source src \\",
  "    --profile-config src/conf/test.config -o .",
  "",
  "# 2. plan a batch, run it; repeat until the planner says nothing is left",
  "python3 $PF/tools/adaptive.py --dims proposal.json --dags dags -o next.tsv",
  "bash $PF/tools/preview_matrix.sh -j 4 nf-core/fetchngs next.tsv dags -- -r 1.13.0 -profile test",
  "",
  "# 3. the model, and the page to check it",
  "python3 $PF/tools/generate.py --name nf-core/fetchngs --dims proposal.json \\",
  "    --runs dags/runs.tsv --source src -o model.json",
  "python3 $PF/viewer/build.py model.json -o model.html",
  "",
  "# 4. publish it with the release",
  "python3 $PF/tools/publish.py model.json --dims proposal.json \\",
  "    -o src/assets/process-flow/channels.json",
]));
children.push(H2("7.2 Choosing what to vary"));
children.push(P("propose.py reads nextflow_schema.json and the code, and proposes every parameter the workflow code tests: enums as choices, booleans as on/off, paths and tested strings as set/unset, comma-separated lists as one switch per value. Plumbing (output, resources, notifications) and parameters the code never tests are left out, with the reason in proposal.json. Each proposed parameter multiplies the previews, so start with the ones that matter most (for nf-core/rnaseq, its eight choice parameters) and note the rest: the published model lists every parameter the code tests that the matrix held fixed, and says its conditions are exact only with those as the test profile has them."));
children.push(P([BOLD("Constraints. "), PLAIN("Where the pipeline refuses a combination (nf-core/rnaseq: screening unmapped reads needs an aligner that makes them), declare it as an implies on the dimension, so the planner stops asking for it.")]));
children.push(H2("7.3 Making the test profile previewable"));
children.push(bullet([BOLD("Remote test data: "), PLAIN("tools/localise_testdata.py downloads the profile's remote files once and writes fixed_args.txt pointing at local copies, so previews never fetch.")]));
children.push(bullet([BOLD("Arguments the same in every run "), PLAIN("(adaptive.py --fixed or --fixed-file): to get past a check that stops a preview, such as nf-core/rnaseq 3.27's --transcript_fasta null. Being the same everywhere, they cannot be mistaken for an effect; the published model records them.")]));
children.push(bullet([BOLD("Empty and null values: "), PLAIN("Nextflow reads --param '' as true, so the matrix driver writes empty strings and nulls to a params file instead. Use null for a path; nf-core's schema rejects an empty path.")]));
children.push(H2("7.4 The published model"));
children.push(P("publish.py drops the per-preview evidence (nf-core/rnaseq: 8.5 MB down to 0.76 MB) and keeps a summary: previews that worked and failed, the arguments fixed in every one, the parameters held, anything the matrix did not settle, and the count of disagreements between conditions and previews (zero). It is stamped with the repository, commit, release and Nextflow version. A run of another commit still uses it, with a warning, and the This run box names where they differ."));
children.push(table([3000, 1500, 1600, 3260], [
  ["Analyser", "Previews", "Elements", "Result"],
  ["nf-core/fetchngs 1.13.0", "14", "117", "every process matches the hand-built model"],
  ["nf-core/rnaseq 3.27.0", "357", "2,289", "every condition agrees with every preview"],
]));
children.push(spacer());

// 8. Troubleshooting
children.push(H1("8. Troubleshooting"));
children.push(table([3600, 5760], [
  ["Symptom", "Likely cause / fix"],
  ["Config parsing failed, Invalid include source, before anything runs", "The release's own config is broken (nf-core/methylseq 4.2.0 includes a file it does not ship). Not process-flow: try another release, or NXF_SYNTAX_PARSER=v1 in front of the command. nextflow config catches this in seconds"],
  ["A task is killed for memory, or Nextflow says it cannot satisfy a request", "Cap resources in a config passed with -c (section 3)"],
  ["no lineage store at .../.lineage", "The run was made without lineage. Use process-flow run, or add lineage.enabled = true to a config"],
  ["no DAG at ...", "Give the run's DAG with --dag, or rerun with process-flow run, which writes it"],
  ["the pipeline's source is not at ...", "The run's pulled source is gone (another machine, a cleaned cache). Give a checkout of the same release with --source"],
  ["nextflow exited with 1; nothing to explore", "The run failed. Fix it and rerun with -resume"],
  ["WARNING: it was built for <commit>, this run is <commit>", "The published model is for another commit. The page still uses it, and names any difference"],
  ["Elements marked unknown on the page", "The code was not plain enough to read, or the run contradicted what was read. Expected for a few percent of operators and channels"],
  ["An old release will not run at all", "Very old nf-core releases use config functions current Nextflow rejects (check_max in nf-core/rnaseq 3.9). Pin a recent release"],
  ["Analyser: previews freeze", "A preview in the background touched the terminal; preview_matrix.sh runs each in its own session, so use it rather than starting previews by hand"],
]));
children.push(spacer());

// 9. Limits
children.push(H1("9. Limits"));
children.push(bullet([PLAIN("A run shows its own route. Elements of routes it did not take appear only from a published model.")]));
children.push(bullet([PLAIN("Lineage records what crossed process boundaries. The items between two operators (after a map or a join) are not shown, only which files passed.")]));
children.push(bullet([PLAIN("Routing per sample inside branch and filter closures is not a condition on the settings (section 6.4).")]));
children.push(bullet([PLAIN("Read from the code, operator and channel conditions are less sure than processes'. A published model removes the doubt for the routes it covers.")]));
children.push(bullet([PLAIN("Nextflow's DAG format is internal and may change between Nextflow releases. process-flow is tested on Nextflow 26.04.")]));

// 10. Further reading
children.push(H1("10. Further reading"));
children.push(P("This guide is generated from the process-flow repository and travels well on its own. These documents live in the repository, and each is the authoritative version of what is summarised here:"));
children.push(table([3200, 6160], [
  ["Document", "What it adds"],
  ["README.md", "Overview, quick start and the repository layout"],
  ["docs/guide.md", "The long-form version of sections 3, 4 and 7, with the Analyser walkthrough on nf-core/fetchngs and what nf-core/rnaseq needed on top"],
  ["examples/", "Pages to open without running anything (nf-core/rnaseq and nf-core/sarek test runs, nf-core/fetchngs), and the two published models"],
  ["schema/README.md", "The channel model: every field, and why it is shaped as it is"],
  ["CHANGELOG.md", "What changed in each release"],
  ["CITATION.cff", "How to cite process-flow"],
]));
children.push(spacer());
children.push(P([BOLD("This document is generated. "), PLAIN("It is built from docs/build_user_guide.js in the repository, so edits made in Word are lost the next time it is rebuilt: change the generator instead. The logo is rendered from the same SVG the viewer shows, and the version on the title page is read from tools/version.py, so both always match the release.")]));

// ---- assemble -------------------------------------------------------------
const doc = new Document({
  creator: "process-flow",
  title: "process-flow User Guide",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Calibri", color: BLUE },
        paragraph: { spacing: { before: 320, after: 160 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 3 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Calibri", color: "2E75B6" },
        paragraph: { spacing: { before: 220, after: 110 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 460, hanging: 280 } } } }] },
    ],
  },
  features: { updateFields: true },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    headers: { default: new Header({ children: [new Paragraph({
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
      children: [new TextRun({ text: "process-flow", color: "808080", size: 18 }),
        new TextRun({ text: "\tUser Guide  ·  version " + VERSION, color: "808080", size: 18 })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Page ", color: "808080", size: 18 }),
        new TextRun({ children: [PageNumber.CURRENT], color: "808080", size: 18 })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUTPUT_DOCX, buf);
  console.log("written", OUTPUT_DOCX, buf.length, "bytes; logo", LOGO_PNG, logoBuffer.length, "bytes");
});
