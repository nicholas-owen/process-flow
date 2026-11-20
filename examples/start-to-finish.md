# Example: from an empty machine to a page you can share

This walks through process-flow start to finish, twice, on real pipelines:

- **Example A** runs nf-core/rnaseq, which Nextflow downloads from GitHub for
  you. This is the usual case.
- **Example B** runs a pipeline you download from GitHub yourself, as a ZIP
  or a clone, and run from a folder on your machine. It uses a small
  single-cell pipeline written in Nextflow's newer strict syntax, which has
  its own two quirks.

You end with `channels.html`: one file showing every process and channel of
the pipeline, and what your run carried through each. If you only want to see
a page first, open one in [the other pages here](README.md); nothing needs
installing for that.

Times and numbers below are from real runs on a laptop with 15 GB of memory
under WSL2.

## 1. Set up once

You need Linux or WSL2, Java, Nextflow, a container engine and Python 3.

| You need | Check | If missing |
|---|---|---|
| Linux, or WSL2 on Windows | `uname -a` | in PowerShell: `wsl --install -d Ubuntu`, then open Ubuntu |
| Java 17 or later | `java -version` | `sudo apt install openjdk-17-jre-headless` |
| Nextflow 25.04 or later | `nextflow -version` | `curl -s https://get.nextflow.io \| bash`, then `sudo mv nextflow /usr/local/bin/` |
| Docker (or Singularity, Conda) | `docker run --rm hello-world` | on WSL2, install Docker Desktop and turn on its WSL integration for your distribution |
| Python 3.8 or later | `python3 --version` | `sudo apt install python3` |

Nextflow 25.04 is the first with data lineage, which process-flow reads.
Pipelines written in the strict syntax (a typed `params { }` block, an
`output { }` block) need 25.10 or later.

Get process-flow:

```bash
git clone https://github.com/nicholas-owen/process-flow.git ~/process-flow
```

Check it runs:

```bash
~/process-flow/bin/process-flow --help
```

To type `process-flow` alone, put its `bin` folder on your PATH:

```bash
echo 'export PATH="$HOME/process-flow/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

Below, `process-flow` means that command; use the full path
`~/process-flow/bin/process-flow` if you have not done that. To update later,
run `git pull` in `~/process-flow`.

**Keep run folders on the Linux filesystem** (your home folder), not under
`/mnt/c` or a synced drive. Nextflow writes a lot of small files, and it is
many times slower on a mounted Windows drive.

## 2. Getting a pipeline from GitHub

There are three ways. Use A unless you have a reason not to.

**A. Let Nextflow download it.** Any GitHub repository is a Nextflow project
name (`owner/repo`). Nextflow pulls it the first time you run it and keeps a
copy under `~/.nextflow/assets`; process-flow finds that copy itself. Always
pin a release with `-r`, so the run can be repeated:

```bash
nextflow pull nf-core/rnaseq -r 3.27.0
```

You don't have to pull first; `run` does it. To see a repository's releases,
newest last:

```bash
git ls-remote --tags https://github.com/nf-core/rnaseq | grep -v '\^{}' | sed 's#.*refs/tags/##' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -5
```

**B. Clone it.** Do this to read or edit the pipeline, or to run an
unreleased branch:

```bash
git clone --depth 1 --branch 3.27.0 https://github.com/nf-core/rnaseq.git ~/pipelines/rnaseq
```

Replace `3.27.0` with a tag or branch name. Then run it by its path
(`~/pipelines/rnaseq/main.nf`), with no `-r`.

**C. Download the ZIP.** On the repository's page choose **Code → Download
ZIP**. WSL sees your Windows Downloads folder at
`/mnt/c/Users/<you>/Downloads`, so unpack from there into your home folder
(`sudo apt install unzip` if the command is missing):

```bash
mkdir -p ~/pipelines && unzip /mnt/c/Users/<you>/Downloads/some-pipeline-main.zip -d ~/pipelines
```

GitHub names the folder `<repo>-main` (or `-master`). Windows may also leave
`*.zip:Zone.Identifier` files beside the ZIP when it is copied into WSL;
they are harmless, and you can delete them. Run it by its path, as in B.

**Before you run any of them,** check that the pipeline's own configuration
parses. It takes seconds, and some releases do not parse on a current
Nextflow (nf-core/methylseq 4.2.0 was missing a file its config includes, and
failed before running anything):

```bash
nextflow config nf-core/rnaseq -r 3.27.0 -profile test,docker | tail -5
```

For a pipeline in a folder, run it from inside the folder, and leave `-r`
out; `-r` tells Nextflow it is a remote project, and it answers *Not a valid
project name*:

```bash
cd ~/pipelines/some-pipeline-main && nextflow config . -profile docker | tail -5
```

A printed config means it parses. An error is the pipeline's, not
process-flow's; try another release.

**Find out what the pipeline needs to run.** nf-core pipelines take
`--input`, `--outdir` and a genome or references, and have a `test` profile
with small data of their own. Others list their parameters in the README,
in `nextflow_schema.json`, or in the `params { }` block at the top of
`main.nf`, and may supply example parameter files (look for a `params/`
folder). `nextflow run owner/repo -r TAG --help` prints an nf-core
pipeline's parameters.

## 3. Example A: nf-core/rnaseq

Make a folder for the run:

```bash
mkdir -p ~/runs/rnaseq && cd ~/runs/rnaseq
```

nf-core test profiles ask for up to 4 CPUs and 15 GB. If your machine has
less than about 16 GB, cap what a task may ask for. This changes how much a
task may ask for, never which processes run or how they are joined:

```bash
echo 'process.resourceLimits = [cpus: 4, memory: 12.GB, time: 6.h]' > limits.config
```

Run the pipeline's test through process-flow. Everything after `run` goes to
`nextflow run` unchanged:

```bash
process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results -c limits.config
```

The first run pulls several gigabytes of container images and takes a while;
the pipeline itself took about 10 minutes here (234 tasks). Nextflow prints
its usual progress. When it finishes, process-flow carries on:

```
process-flow: run serene_aryabhata: nf-core/rnaseq 3.27.0 (a1fcdddd3b), 234 tasks
process-flow: no published model: building one from the run's DAG and the code
process-flow: conditions: 1353 read, 213 read, some settings undecided, 43 contradicted by the run
serene_aryabhata: 234 tasks in 65 processes; 140 input ports and 175 emits harvested; 324 process-boundary edges filled, 163 operator edges given their files
  processes: 67 expected under the run's settings, 65 ran, 67 wired
  wired but no task ran (2): PRESEQ_LCEXTRAP, SAMTOOLS_INDEX
process-flow: wrote results/pipeline_info/channels.html
```

Read it like this: process-flow found no model published by the pipeline's
authors, so it read each condition from the code (*read*); a few it could not
fully decide (*undecided*), and 43 elements the run showed to exist although
the code's conditions said they should not, so those show as unknown rather
than wrong. Two processes were wired into the run but received no data. The
page is `results/pipeline_info/channels.html`. From Windows, a WSL folder is
reachable as `\\wsl$\Ubuntu\home\<you>\runs\rnaseq\results\pipeline_info\channels.html`
(replace `Ubuntu` with your distribution's name from `wsl -l`).

If the run fails, nothing is built. Fix the cause and rerun the same command
with `-resume` added: tasks that already finished come from Nextflow's cache,
and process-flow counts them.

## 4. Example B: a pipeline you downloaded

This one is a small single-cell RNA-seq pipeline (10 processes: import, QC,
filter, normalise, highly variable genes, PCA, UMAP, clustering and plots),
[kevinrue/biofair-nextflow-pipeline](https://github.com/kevinrue/biofair-nextflow-pipeline).
Download its ZIP (Code, then Download ZIP) and unpack it, as in 2C, to
`~/pipelines/biofair-nextflow-pipeline-main`. It has no
`nextflow_schema.json`, a typed `params { }` block, and an `output { }` block.
It comes with example parameter files in `params/` (`hdf5.yml` and `mtx.yml`,
each pointing at a small public 10x dataset).

First, look at what is in it:

```bash
ls ~/pipelines/biofair-nextflow-pipeline-main
```

Check its config parses, from inside the folder and with no `-r`:

```bash
cd ~/pipelines/biofair-nextflow-pipeline-main && nextflow config . -profile docker | tail -5
```

Run it from a separate folder, so its `work/` and `results/` stay out of the
pipeline's folder:

```bash
mkdir -p ~/runs/biofair && cd ~/runs/biofair
```

```bash
PIPE=~/pipelines/biofair-nextflow-pipeline-main
```

```bash
process-flow run $PIPE/main.nf -profile docker -params-file $PIPE/params/hdf5.yml --metadata_filters $PIPE/data/metadata-filters.json -output-dir results
```

Three things in that command are worth knowing, because each one failed
before it worked:

- **`-output-dir`, not `--outdir`.** A pipeline in the strict syntax rejects
  a parameter it does not declare, and this one declares no `outdir`. With
  `--outdir` it stops at launch with *Parameter 'outdir' was specified ... but
  is not declared*. Where its results go is set with Nextflow's
  `-output-dir`. process-flow accepts either.
- **`--metadata_filters` with a full path.** The example parameter file gives
  `data/metadata-filters.json`, and Nextflow resolves a relative path from the
  folder you launch in, not from the pipeline's. From `~/runs/biofair` that
  file does not exist, so name it in full. A command-line value overrides the
  parameter file.
- **Run it by the path to `main.nf`, with no `-r`.** `-r` is for remote
  projects.

The pipeline took about 6 minutes (10 tasks, plus pulling its image the first
time). process-flow then reports:

```
process-flow: run reverent_allen: biofair-nextflow-pipeline, 10 tasks
process-flow: no published model: building one from the run's DAG and the code
reverent_allen: 10 tasks in 10 processes; 33 input ports and 14 emits harvested; 43 process-boundary edges filled, 0 operator edges given their files
  processes: 10 expected under the run's settings, 10 ran, 10 wired
process-flow: wrote results/pipeline_info/channels.html
```

The page has no filters, since there is no schema to list parameters from,
but it shows the whole graph and what each channel carried: the `meta` map
(`id`), the `[meta, infile, metadata_filters]` tuple after the `map`, and the
real items from this run, such as `[[id:test_sample], [outfile.h5ad]]`. The
end points name the output actually published (`qc_table`, `plot_umap`,
`plot_var_explained`). "0 operator edges" is correct here: no two operators
are joined directly, so there is nothing between them to describe.

## 5. What to look at in the page

Open the page and try these, in this order:

1. **Press *Show this run's settings*** in the *This run* box at the top of
   the left panel. Every filter is set to what your run used. For
   nf-core/rnaseq the sections show *6 not default* under *Reference genome
   options*: where the test profile differs from a default run.
2. **Click a channel** going into a process you care about (for rnaseq, the
   one into STAR_ALIGN). The right-hand panel shows its tuple shape, the
   `meta` keys, whether it is a queue of one item per sample or a value given
   to every task, and a worked example with the run's real items.
3. **Click a process** and read *this run*: how many tasks it ran, or that it
   was wired but received nothing.
4. **Tick a route** (for rnaseq, `hisat2`) to see which processes and
   channels another aligner would use. These come from the code, not from
   your run; they are marked *source* until the pipeline publishes a model.
5. **Find an option** in the search box above the filters, and turn it on or
   off to see what it switches in or out.

The labels beside each value say where it came from: *harvested* (your run),
*declared* (the module's declaration), *inferred*, *preview* (a model proven by
the pipeline's authors), *source* (read from the code), *unknown*. The
[user guide](../process-flow_User_Guide.docx), section 5, lists every row of
the panels.

## 6. Rebuild, share and tidy up

**Rebuild** the page from the run you already have, with no pipeline re-run,
for instance after updating process-flow. In the folder you launched from:

```bash
process-flow explore
```

**Share.** `channels.html` is one self-contained file: the layout library,
the logo and the data are inside it, nothing loads from the internet, and it
holds no local paths. Send just that file (zip it if a mail client blocks
`.html`). The page does contain what flowed through your channels, sample
IDs, `meta` values and file names, with up to six example items per channel.
For a run on real or sensitive samples, open it first and treat it like a
results table.

**Tidy up.** A run leaves these in the folder you launched from:

| Folder | What | Safe to delete? |
|---|---|---|
| `results/` | the pipeline's outputs and the page | keep the page; the rest is yours |
| `.lineage/` | what each task received and produced | keep it if you may want to rebuild the page |
| `work/` | every task's files, often gigabytes | yes, once the page is built: it only stops `-resume` |
| `.nextflow/`, `.process-flow/` | Nextflow's cache and process-flow's config | yes, with `work/` |

## 7. When something goes wrong

| What you see | Cause and fix |
|---|---|
| `Not a valid project name: /path/to/folder` | `-r` given with a local path, or the path is wrong. Leave `-r` out, and check the folder with `ls` (a ZIP often unpacks to a folder inside a folder) |
| `Config parsing failed` or `Invalid include source` before anything runs | the release's own config is broken. Another release is the fix; `nextflow config` catches it in seconds |
| `Parameter 'outdir' was specified ... but is not declared` | strict-syntax pipeline; use `-output-dir results` (Example B) |
| `... has no workflow run: the run most likely failed before any task started` | the run never started. process-flow prints the last error from `.nextflow.log`; fix it and rerun |
| `Process requirement exceeds available memory`, or a task killed | give the run less to ask for: a `limits.config` (Example A) |
| `No such file` for a path from a parameter file | a relative path, resolved from where you launched. Give it in full |
| The run failed part-way | rerun the same command with `-resume`; finished tasks are reused and counted |
| An old release will not run | very old nf-core releases use config functions current Nextflow rejects. Use a recent release |

More in the user guide, section 8.

## 8. Next

- To see routes your run did not take with every condition proven, rather
  than read from the code, use a model the pipeline's authors published, or
  make one: `docs/guide.md` walks through the **Analyser**.
- To add a pipeline's authors' model to your page, pass it with
  `process-flow explore --model FILE`; [published/](published/)
  has two.
