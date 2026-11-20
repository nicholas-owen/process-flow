"""How a workflow's use of a process's emits is read (tools/ports.py), in the
old syntax and in Nextflow's newer strict syntax.

    python tools/test_ports.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ports import _uses
from pf import pipeline_name

OLD = """
workflow FOO {
    RNA_QC(ch_reads)
    ch_filtered = RNA_QC.out.outfile.map { m, f -> [m, f] }
    SCE_FILTER(RNA_QC.out.outfile)
}
"""

# the call's result is a variable; `publish:` only names outputs
STRICT = """
workflow {
    main:
    def qc = RNA_QC(counts.outfile, 1)
    def filtered = qc.outfile.map { m, f -> [m, f] }
    def other = SCE_FILTER(qc.outfile)
    def joined = normalized.outfile.join(qc.extra)

    publish:
    qc_table = qc.qc_table
}
"""


def check(ok, what):
    print(("ok     " if ok else "FAILED ") + what)
    return ok


def main():
    old = _uses(OLD, "RNA_QC")
    new = _uses(STRICT, "RNA_QC")
    good = [
        check(("op", "map") in old["outfile"] and ("var", "ch_filtered") in old["outfile"], "old syntax: X.out.emit, followed by an operator and an assignment"),
        check(("call", "SCE_FILTER") in old["outfile"], "old syntax: X.out.emit passed to a process"),
        check(("op", "map") in new["outfile"], "strict syntax: qc.emit, followed by an operator"),
        check(("call", "SCE_FILTER") in new["outfile"], "strict syntax: qc.emit passed to a process"),
        check(("op", "join") in new["extra"], "strict syntax: qc.emit as an operator's argument"),
        check("qc_table" not in new, "strict syntax: publish: is not a use, so the emit stays a bare end point"),
        check(pipeline_name({"projectName": "main.nf"}, "/x/biofair-nextflow-pipeline-main") == "biofair-nextflow-pipeline",
              "a local script is named for its folder, without the GitHub -main"),
        check(pipeline_name({"projectName": "nf-core/rnaseq"}, "/x/y") == "nf-core/rnaseq", "a pulled pipeline keeps its project name"),
    ]
    sys.exit(0 if all(good) else 1)


if __name__ == "__main__":
    main()
