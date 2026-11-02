"""Generate the fixture result directories under ``<repo>/fixtures`` from the brief's formats.

Run: ``python tests/fixtures/build.py``. ``tests/test_fixtures.py`` checks the committed files are
up to date. All people and organisations named here are fictional.

Layout:
  RUN_2606/   one run: PASS (5156), WARN (5157), FAIL (5158), report:false without documents (5159)
              and report:false with metrics only (5160); run.json and samplesheet.csv
  RUN_2607/   a second run with 260630_5156 re-sequenced (sample in two runs), no run.json
  orders/     ZL_2026_001.order.json
  metadata/   metadata.csv (run date, sample metadata, order link)
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "fixtures"
DICTIONARY = REPO / "backend" / "src" / "qcdb" / "data" / "metric_dictionary.psv"

UNITS: dict[str, str] = {}
for _line in DICTIONARY.read_text(encoding="utf-8").splitlines():
    _key, _unit = _line.split("|")[:2]
    UNITS[_key] = _unit

NAMESPACES = {
    "fastp": "reads",
    "kraken2": "composition",
    "bracken": "composition",
    "sylph": "composition",
    "quast": "assembly",
    "seqkit": "assembly",
    "seqkit_contigs": "assembly",
    "checkm": "assembly",
    "checkm2": "assembly",
    "mosdepth": "assembly",
}
VERSIONS = {
    "fastp": "1.1.0",
    "kraken2": "2.1.3",
    "bracken": "3.0",
    "sylph": "0.8.1",
    "quast": "5.2.0",
    "seqkit": "2.8.2",
    "seqkit_contigs": "2.8.2",
    "checkm": "1.2.3",
    "checkm2": "1.0.2",
    "mosdepth": "0.3.8",
    "chewbbaca": "3.3.10",
    "mlst": "2.23.0",
    "seqsero2": "1.3.1",
    "ectyper": "2.0.0",
    "amrfinder": "4.0.3",
    "abricate_plasmidfinder": "1.1.0",
    "abricate_resfinder": "1.1.0",
}
DB_VERSIONS = {
    "kraken2": "k2_standard_20240605",
    "bracken": "k2_standard_20240605",
    "amrfinder": "2024-07-22.1",
    "mlst": "2024-06-01",
    "checkm2": "uniref100.KO.1",
    "abricate_plasmidfinder": "2024-03-15",
    "abricate_resfinder": "2024-03-15",
}
THRESHOLDS_V1 = "52d7e4134f2e8a2a7e72d7d2e0b10dafe114ad4b817c154b2d4c0c865eff7643"
THRESHOLDS_V2 = hashlib.sha256(b"qc_thresholds.yml v2 (fixture)").hexdigest()
D = Decimal


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def dumps(doc: Any) -> str:
    """Compact-ish JSON; Decimals written verbatim so fixtures carry exactly 4 decimals."""

    def enc(v: Any) -> str:
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dict):
            return "{" + ",".join(f"{json.dumps(k)}:{enc(x)}" for k, x in v.items()) + "}"
        if isinstance(v, list):
            return "[" + ",".join(enc(x) for x in v) + "]"
        return json.dumps(v, ensure_ascii=False)

    return enc(doc) + "\n"


def metrics_doc(
    sample: str,
    tool: str,
    values: dict[str, Any],
    *,
    status: str = "ok",
    messages: list[str] | None = None,
    data: dict[str, Any] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = {"tool": tool, "tool_version": version or VERSIONS[tool]}
    if tool in DB_VERSIONS:
        source["database_version"] = DB_VERSIONS[tool]
    return {
        "schema_version": "1.0",
        "sample_id": sample,
        "namespace": NAMESPACES.get(tool, "characterisation"),
        "source": source,
        "parser": {"name": "qcmetrics", "version": "1.0.0"},
        "status": status,
        "messages": messages or [],
        "inputs": [{"path": f"{sample}.{tool}.out", "sha256": sha(f"{sample}.{tool}.raw")}],
        "metrics": {k: {"value": v, "unit": UNITS[f"{tool}.{k}"]} for k, v in values.items()},
        "data": data if data is not None else {},
    }


def fastp(
    pairs_before: int,
    pairs_after: int,
    bases_before: int,
    bases_after: int,
    q30_before: str,
    q30_after: str,
    *,
    duplication: str | None,
) -> dict[str, Any]:
    v: dict[str, Any] = {
        "bases_after_filter": bases_after,
        "bases_before_filter": bases_before,
        "insert_size_peak": 252,
        "mean_read_length_after_filter": D("145.5"),
        "pct_adapter_trimmed_reads": D("7.6867"),
        "pct_bases_after_filter": (D(bases_after) * 100 / D(bases_before)).quantize(D("0.0001")),
        "pct_gc_after_filter": D("50.5987"),
        "pct_q30_after_filter": D(q30_after),
        "pct_q30_before_filter": D(q30_before),
        "pct_reads_passed_filter": (D(pairs_after) * 100 / D(pairs_before)).quantize(D("0.0001")),
        "read_length": D("151.0"),
        "read_pairs_after_filter": pairs_after,
        "read_pairs_before_filter": pairs_before,
    }
    if duplication is not None:
        v["pct_duplication"] = D(duplication)
    return v


def depth(bases_after: int, assembly_length: int) -> Decimal:
    return (D(bases_after) / D(assembly_length)).quantize(D("0.0001"))


def check(
    metric: str,
    value: Any,
    unit: str | None,
    rule: dict[str, Any],
    status: str,
    reason: str | None,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "unit": unit,
        "rule": rule,
        "required": required,
        "status": status,
        "reason": reason,
    }


def qc_doc(
    sample: str,
    verdict: str,
    metric_files: dict[str, tuple[str, str, str]],
    checks: list[dict[str, Any]],
    *,
    species: str,
    taxid: int,
    profile: str,
    thresholds_sha: str,
    reasons: list[str],
    unused: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "sample_id": sample,
        "evaluator": {"name": "qceval", "version": "1.0.0"},
        "verdict": verdict,
        "thresholds": {
            "file": "qc_thresholds.yml",
            "sha256": thresholds_sha,
            "profile": profile,
            "read_length_profile": "2x150",
            "species": species,
            "chain": [profile, "read_length:2x150", f"species:{species}"],
        },
        "context": {
            "expected_taxid": taxid,
            "read_length": D("151.0"),
            "depth_basis": "seqkit.total_length",
        },
        "checks": checks,
        "reasons": reasons,
        "advisory": [c["reason"] for c in checks if c["status"] == "NA"],
        "notes": [],
        "unused_inputs": unused,
        "inputs": [
            {"path": name, "tool": tool, "namespace": ns, "status": st, "sha256": digest}
            for tool, (name, digest, st) in sorted(metric_files.items())
            for ns in [NAMESPACES.get(tool, "characterisation")]
        ],
    }


def report_doc(
    sample: str, run_id: str, meta: dict[str, str], species: dict[str, Any], tools: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "sample_id": sample,
        "run_id": run_id,
        "generator": {"name": "samplereport", "version": "1.0.0"},
        "meta": meta,
        "qc": {},
        "basic": {},
        "client_basic": {},
        "criteria": [],
        "typing": {"species": species},
        "stages": [],
        "contigs": {},
        "composition": {},
        "software": {
            "pipeline": "dnw/vistula",
            "pipeline_version": "v1.0.0dev",
            "nextflow_version": "26.04.6",
            "groups": [
                {
                    "stage": "Trimming i filtracja odczytów",
                    "tools": [
                        {"tool": "fastp", "label": "fastp", "versions": ["1.1.0"], "databases": []}
                    ],
                },
                {
                    "stage": "Składanie genomu",
                    "tools": [
                        {
                            "tool": "spades",
                            "label": "SPAdes",
                            "versions": ["4.0.0"],
                            "databases": [],
                        }
                    ],
                },
            ],
            "other": [
                {"tool": t, "label": t, "versions": [VERSIONS[t]], "databases": []}
                for t in tools
                if t not in ("fastp",)
            ],
        },
    }


SPECIES_SE = {
    "available": True,
    "status": "ok",
    "messages": [],
    "expected": "Salmonella enterica",
    "name": "Salmonella enterica",
    "pct": D("99.713"),
    "taxid": 28901,
    "source": "bracken",
    "match": True,
}
SPECIES_EC = {
    "available": True,
    "status": "ok",
    "messages": [],
    "expected": "Escherichia coli",
    "name": "Escherichia coli",
    "pct": D("97.4012"),
    "taxid": 562,
    "source": "bracken",
    "match": True,
}

COLUMNS = [
    ("raw_reads", "raw", "Odczyty (surowe)", "reads", None),
    ("raw_bases", "raw", "Zasady (surowe)", "bp", "Mb"),
    ("raw_q30", "raw", "Q30 (surowe)", "percent", None),
    ("raw_read_length", "raw", "Długość odczytu", "bp", None),
    ("reads", "after QC", "Odczyty po QC", "reads", None),
    ("bases", "after QC", "Zasady po QC", "bp", "Mb"),
    ("q30", "after QC", "Q30 po QC", "percent", None),
    ("trimmed_read_length", "after QC", "Długość po przycięciu", "bp", None),
    ("pct_reads_passed", "after QC", "% odczytów po filtrze", "percent", None),
    ("n_contigs", "assembly", "Kontigi", "contigs", None),
    ("assembly_length", "assembly", "Długość złożenia", "bp", "Mb"),
    ("n50", "assembly", "N50", "bp", "kb"),
    ("gc", "assembly", "GC", "percent", None),
    ("depth", "assembly", "Pokrycie", "x", None),
    ("completeness", "assembly", "Kompletność", "percent", None),
    ("contamination", "assembly", "Zanieczyszczenie", "percent", None),
]


class Writer:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, dict[str, tuple[str, str, str]]] = {}

    def write(self, name: str, doc: Any) -> str:
        text = dumps(doc)
        (self.dir / name).write_text(text, encoding="utf-8")
        return hashlib.sha256(text.encode()).hexdigest()

    def metrics(self, doc: dict[str, Any]) -> None:
        sample, tool = doc["sample_id"], doc["source"]["tool"]
        name = f"{sample}.{tool}.metrics.json"
        digest = self.write(name, doc)
        self.files.setdefault(sample, {})[tool] = (name, digest, doc["status"])


def amr_hits() -> list[dict[str, Any]]:
    def hit(
        symbol: str,
        name: str,
        type_: str,
        subtype: str,
        cls: str,
        start: int,
        method: str = "ALLELEX",
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "name": name,
            "type": type_,
            "subtype": subtype,
            "class": cls,
            "subclass": cls,
            "method": method,
            "pct_identity": D("100.0"),
            "pct_coverage": D("100.0"),
            "scope": "core" if type_ == "AMR" else "plus",
            "contig": "NODE_4_length_479908_cov_40.066152",
            "strand": "+",
            "accession": f"WP_{start:09d}.1",
            "start": start,
            "stop": start + 860,
        }

    return [
        hit(
            "blaTEM-1",
            "class A broad-spectrum beta-lactamase TEM-1",
            "AMR",
            "AMR",
            "BETA-LACTAM",
            101201,
        ),
        hit(
            "aph(3'')-Ib",
            "aminoglycoside O-phosphotransferase APH(3'')-Ib",
            "AMR",
            "AMR",
            "AMINOGLYCOSIDE",
            120400,
        ),
        hit(
            "sul2",
            "sulfonamide-resistant dihydropteroate synthase Sul2",
            "AMR",
            "AMR",
            "SULFONAMIDE",
            130020,
        ),
        hit(
            "tet(B)",
            "tetracycline efflux MFS transporter Tet(B)",
            "AMR",
            "AMR",
            "TETRACYCLINE",
            140500,
        ),
        hit(
            "gyrA_D87N",
            "Salmonella quinolone resistant GyrA",
            "AMR",
            "POINT",
            "QUINOLONE",
            160000,
            method="POINTX",
        ),
        hit(
            "golT",
            "gold/copper-translocating P-type ATPase GolT",
            "STRESS",
            "METAL",
            "GOLD",
            170000,
        ),
        hit(
            "sopB",
            "type III secretion system effector SopB",
            "VIRULENCE",
            "VIRULENCE",
            "VIRULENCE",
            180000,
        ),
    ]


def build_run_2606() -> None:
    w = Writer(OUT / "RUN_2606")
    run_id = "RUN_2606"

    # ---- 260630_5156: PASS, Salmonella (the brief's examples)
    s = "260630_5156"
    w.metrics(
        metrics_doc(
            s,
            "fastp",
            fastp(
                1428832, 1398373, 431507264, 407731967, "87.7232", "89.6542", duplication="0.7496"
            ),
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "kraken2",
            {
                "n_fragments_total": 1398373,
                "pct_unclassified": D("1.2034"),
                "pct_classified": D("98.7966"),
                "pct_human": D("0.0012"),
                "pct_bacteria": D("98.7001"),
                "pct_viruses": D("0.0101"),
            },
            data={
                "top_species": [
                    {
                        "name": "Salmonella enterica",
                        "taxid": 28901,
                        "fragments": 1371000,
                        "pct": D("98.0431"),
                    }
                ]
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "bracken",
            {
                "top_species": "Salmonella enterica",
                "top_species_taxid": 28901,
                "pct_top_species": D("99.713"),
                "second_species": "Escherichia coli",
                "pct_second_species": D("0.198"),
                "n_species_above_1pct": 1,
                "shannon_index": D("0.0213"),
            },
            data={
                "abundances": [
                    {
                        "name": "Salmonella enterica",
                        "taxid": 28901,
                        "reads": 1392000,
                        "pct": D("99.713"),
                    },
                    {"name": "Escherichia coli", "taxid": 562, "reads": 2760, "pct": D("0.198")},
                ]
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "sylph",
            {
                "top_species": "s__Salmonella enterica",
                "pct_top_species": D("99.1203"),
                "pct_top_species_reads": D("98.7012"),
                "second_species": "s__Escherichia coli",
                "pct_second_species": D("0.8797"),
                "n_species": 2,
                "n_species_above_1pct": 1,
                "shannon_index": D("0.0503"),
                "top_genome": "GCF_000006945.2",
                "top_genome_ani": D("99.8213"),
                "taxonomies_used": "/mnt/ngs_data/sylph_db/globdb_r226_sylph_tax.tsv",
                "top_genome_coverage": D("70.3121"),
            },
            data={
                "sample": "fq/trim/260630_5156_S1_L001_R1_001.fastq.gz",
                "taxonomies_used": "/mnt/ngs_data/sylph_db/globdb_r226_sylph_tax.tsv",
                "species": [],
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "quast",
            {
                "n_contigs": 120,
                "n_contigs_all": 449,
                "total_length": 5401234,
                "total_length_all": 5443271,
                "largest_contig": 479908,
                "n50": 95966,
                "l50": 18,
                "pct_gc": D("50.52"),
                "n_per_100kbp": D("0.0"),
            },
            data={"assembly": "contigs"},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "seqkit",
            {
                "n_contigs": 449,
                "total_length": 5443271,
                "largest_contig": 479908,
                "shortest_contig": 56,
                "mean_contig_length": D("12123.1091"),
                "n50": 95966,
                "l50": 18,
                "pct_gc": D("50.53"),
                "n_bases": 0,
                "n_per_100kbp": D("0.0"),
            },
            data={
                "file": "260630_5156.contigs.fa",
                "type": "DNA",
                "Q1": "312.0",
                "Q2": "1450.0",
                "Q3": "9870.0",
                "sum_gap": "0",
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "seqkit_contigs",
            {"n_contigs": 449, "pct_gc_stdev": D("2.1345")},
            data={"contigs": [{"name": "NODE_1", "length": 479908, "pct_gc": D("52.11")}]},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "checkm",
            {
                "pct_completeness": D("99.5"),
                "pct_contamination": D("0.32"),
                "pct_strain_heterogeneity": D("0.0"),
                "marker_lineage": "f__Enterobacteriaceae (UID5103)",
            },
            data={"bin": "260630_5156", "# genomes": "134", "5+": "0"},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "checkm2",
            {"pct_completeness": D("99.87"), "pct_contamination": D("0.45")},
            data={"genome": "260630_5156"},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "mosdepth",
            {
                "reference_length": 5443271,
                "n_contigs": 449,
                "aligned_bases": 407730000,
                "mean_depth": D("74.9054"),
                "max_depth": 412,
                "n_contigs_zero_depth": 3,
                "pct_bases_ge_1x": D("100.0"),
                "pct_bases_ge_10x": D("99.0"),
                "pct_bases_ge_20x": D("99.0"),
                "pct_bases_ge_30x": D("98.0"),
                "pct_bases_ge_50x": D("90.0"),
                "pct_bases_ge_100x": D("12.0"),
            },
            data={
                "contigs": [
                    {"name": "NODE_1", "length": 479908, "mean_depth": D("75.1"), "max_depth": 300}
                ]
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "chewbbaca",
            {
                "n_loci": 3002,
                "n_loci_called": 2980,
                "pct_loci_called": D("99.2672"),
                "n_exc": 2950,
                "n_inf": 30,
                "n_lnf": 10,
                "n_plot": 5,
                "n_lotsc": 1,
                "n_niph": 3,
                "n_alm": 2,
                "n_asm": 1,
                "n_pama": 0,
                "n_missing": 22,
                "n_cds_total": 4800,
                "n_cds_classified": 2990,
                "n_cds_invalid": 12,
            },
            data={"genome": "260630_5156"},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "mlst",
            {
                "scheme": "senterica_achtman_2",
                "sequence_type": "19",
                "n_alleles_exact": 7,
                "n_alleles_novel": 0,
                "n_alleles_partial": 0,
                "n_alleles_missing": 0,
                "n_alleles_multiple": 0,
            },
            data={
                "file": "260630_5156.contigs.fa",
                "alleles": {
                    "aroC": "10",
                    "dnaN": "7",
                    "hemD": "12",
                    "hisD": "9",
                    "purE": "5",
                    "sucA": "9",
                    "thrA": "2",
                },
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "seqsero2",
            {
                "serotype": "Typhimurium",
                "antigenic_profile": "4:i:1,2",
                "o_antigen": "4",
                "h1_antigen": "i",
                "h2_antigen": "1,2",
                "predicted_identification": (
                    "Salmonella enterica subspecies enterica (subspecies I)"
                ),
            },
            data={"sample": "260630_5156"},
        )
    )
    w.metrics(
        metrics_doc(
            s, "ectyper", {}, status="skipped", messages=["ECTyper runs only for Escherichia coli"]
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "amrfinder",
            {
                "n_amr_classes": 5,
                "n_amr_genes": 4,
                "n_point_mutations": 1,
                "n_stress": 1,
                "n_virulence": 1,
            },
            data={
                "hits": amr_hits(),
                "amr_classes": [
                    "AMINOGLYCOSIDE",
                    "BETA-LACTAM",
                    "QUINOLONE",
                    "SULFONAMIDE",
                    "TETRACYCLINE",
                ],
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "abricate_plasmidfinder",
            {},
            status="empty",
            data={"database": "plasmidfinder", "file": "260630_5156.contigs.fa", "hits": []},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "abricate_resfinder",
            {
                "n_hits": 4,
                "n_genes": 4,
                "n_contigs": 2,
                "min_pct_identity": D("99.88"),
                "min_pct_coverage": D("100.0"),
            },
            data={
                "database": "resfinder",
                "file": "260630_5156.contigs.fa",
                "hits": [
                    {
                        "gene": "blaTEM-1B",
                        "contig": "NODE_4",
                        "start": 101201,
                        "end": 102061,
                        "pct_coverage": D("100.0"),
                        "pct_identity": D("100.0"),
                        "accession": "AY458016",
                        "product": "blaTEM-1B",
                    }
                ],
            },
        )
    )
    checks_5156 = [
        check(
            "species_match",
            "Salmonella enterica (taxid 28901)",
            None,
            {"expected_taxid": 28901},
            "PASS",
            None,
        ),
        check(
            "fastp.pct_q30_before_filter",
            D("87.7232"),
            "percent",
            {"min": 80, "warn_min": 85},
            "PASS",
            None,
        ),
        check("derived.depth", D("74.9057"), "x", {"min": 30, "warn_min": 35}, "PASS", None),
        check("seqkit.n_contigs", 449, "contigs", {"max": 700, "warn_max": 550}, "PASS", None),
        check(
            "checkm2.pct_contamination",
            D("0.45"),
            "percent",
            {"max": 10, "warn_max": 5},
            "PASS",
            None,
        ),
        check(
            "derived.pct_cgmlst_missing",
            D("0.7328"),
            "percent",
            {"max": 5, "warn_max": 3},
            "PASS",
            None,
        ),
    ]
    w.write(
        f"{s}.qc.json",
        qc_doc(
            s,
            "PASS",
            w.files[s],
            checks_5156,
            species="Salmonella enterica",
            taxid=28901,
            profile="bacteria_wgs",
            thresholds_sha=THRESHOLDS_V1,
            reasons=[],
            unused=["abricate_plasmidfinder", "amrfinder"],
        ),
    )
    w.write(
        f"{s}.report.json",
        report_doc(
            s,
            run_id,
            {
                "run_id": run_id,
                "zleceniodawca": "Jan Kowalski",
                "expected_species": "Salmonella enterica",
            },
            SPECIES_SE,
            sorted(w.files[s]),
        ),
    )

    # ---- 260630_5157: WARN (the brief's WARN example), conditional metrics absent, a null
    s = "260630_5157"
    fp = fastp(1310000, 1281000, 395620000, 372771000, "81.0", "84.1203", duplication=None)
    w.metrics(metrics_doc(s, "fastp", fp))
    w.metrics(
        metrics_doc(
            s,
            "kraken2",
            {},
            status="missing",
            messages=["kraken2 report not found for 260630_5157"],
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "bracken",
            {
                "top_species": "Salmonella enterica",
                "top_species_taxid": 28901,
                "pct_top_species": D("98.9021"),
                "second_species": None,
                "pct_second_species": D("0.0"),
                "n_species_above_1pct": 1,
                "shannon_index": D("0.0012"),
            },
            messages=["only one species above the reporting threshold"],
            data={
                "abundances": [
                    {
                        "name": "Salmonella enterica",
                        "taxid": 28901,
                        "reads": 1266000,
                        "pct": D("98.9021"),
                    }
                ]
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "seqkit",
            {
                "n_contigs": 612,
                "total_length": 4976500,
                "largest_contig": 301233,
                "shortest_contig": 61,
                "mean_contig_length": D("8131.5359"),
                "n50": 41020,
            },
            version="2.3.0",
            data={
                "file": "260630_5157.contigs.fa",
                "type": "DNA",
                "Q1": "280.0",
                "Q2": "1200.0",
                "Q3": "7800.0",
                "sum_gap": "0",
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "quast",
            {
                "n_contigs": 210,
                "n_contigs_all": 612,
                "total_length": 4901000,
                "total_length_all": 4976500,
                "largest_contig": 301233,
                "n50": 41020,
                "l50": 38,
                "pct_gc": D("52.07"),
                "n_per_100kbp": D("1.25"),
            },
            data={"assembly": "contigs"},
        )
    )
    w.metrics(
        metrics_doc(s, "checkm2", {"pct_completeness": D("98.12"), "pct_contamination": D("1.9")})
    )
    w.metrics(
        metrics_doc(
            s,
            "mlst",
            {
                "scheme": "senterica_achtman_2",
                "sequence_type": None,
                "n_alleles_exact": 6,
                "n_alleles_novel": 1,
                "n_alleles_partial": 0,
                "n_alleles_missing": 0,
                "n_alleles_multiple": 0,
            },
            messages=["no ST assigned: novel allele combination"],
            data={"file": "260630_5157.contigs.fa", "alleles": {"aroC": "~10", "dnaN": "7"}},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "amrfinder",
            {
                "n_amr_classes": 0,
                "n_amr_genes": 0,
                "n_point_mutations": 0,
                "n_stress": 0,
                "n_virulence": 0,
            },
            data={"hits": [], "amr_classes": []},
        )
    )
    d5157 = depth(372771000, 4976500)
    checks_5157 = [
        check(
            "species_match",
            "Salmonella enterica (taxid 28901)",
            None,
            {"expected_taxid": 28901},
            "PASS",
            None,
        ),
        check(
            "fastp.pct_q30_before_filter",
            D("81.0"),
            "percent",
            {"min": 80, "warn_min": 85},
            "WARN",
            "81 < 85 (warn_min)",
        ),
        check("derived.depth", d5157, "x", {"min": 30, "warn_min": 35}, "PASS", None),
        check(
            "kraken2.pct_unclassified",
            None,
            "percent",
            {"max": 75, "warn_max": 50},
            "NA",
            "no kraken2 document",
            required=False,
        ),
        check(
            "seqkit.n_contigs",
            612,
            "contigs",
            {"max": 700, "warn_max": 550},
            "WARN",
            "612 > 550 (warn_max)",
        ),
    ]
    w.write(
        f"{s}.qc.json",
        qc_doc(
            s,
            "WARN",
            w.files[s],
            checks_5157,
            species="Salmonella enterica",
            taxid=28901,
            profile="bacteria_wgs",
            thresholds_sha=THRESHOLDS_V1,
            reasons=[
                "fastp.pct_q30_before_filter: 81 < 85 (warn_min)",
                "seqkit.n_contigs: 612 > 550 (warn_max)",
            ],
            unused=["amrfinder"],
        ),
    )
    w.write(
        f"{s}.report.json",
        report_doc(
            s,
            run_id,
            {"run_id": run_id, "Zleceniodawca": "Jan Kowalski"},
            SPECIES_SE,
            sorted(w.files[s]),
        ),
    )

    # ---- 260630_5158: FAIL, E. coli, contamination above 100, a failed tool
    s = "260630_5158"
    w.metrics(
        metrics_doc(
            s,
            "fastp",
            fastp(
                1502000, 1470100, 453604000, 427800000, "88.9012", "90.2011", duplication="1.2033"
            ),
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "bracken",
            {
                "top_species": "Escherichia coli",
                "top_species_taxid": 562,
                "pct_top_species": D("97.4012"),
                "second_species": "Klebsiella pneumoniae",
                "pct_second_species": D("2.1009"),
                "n_species_above_1pct": 2,
                "shannon_index": D("0.1301"),
            },
            data={
                "abundances": [
                    {
                        "name": "Escherichia coli",
                        "taxid": 562,
                        "reads": 1431900,
                        "pct": D("97.4012"),
                    },
                    {
                        "name": "Klebsiella pneumoniae",
                        "taxid": 573,
                        "reads": 30880,
                        "pct": D("2.1009"),
                    },
                ]
            },
        )
    )
    w.metrics(metrics_doc(s, "quast", {}, status="failed", messages=["QUAST exited with status 1"]))
    w.metrics(
        metrics_doc(
            s,
            "seqkit",
            {
                "n_contigs": 1890,
                "total_length": 9822000,
                "largest_contig": 210000,
                "shortest_contig": 52,
                "mean_contig_length": D("5196.8254"),
                "n50": 18400,
                "l50": 140,
                "pct_gc": D("51.88"),
                "n_bases": 1200,
                "n_per_100kbp": D("12.2174"),
            },
            data={
                "file": "260630_5158.contigs.fa",
                "type": "DNA",
                "Q1": "200.0",
                "Q2": "900.0",
                "Q3": "4300.0",
                "sum_gap": "0",
            },
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "checkm",
            {
                "pct_completeness": D("100.0"),
                "pct_contamination": D("145.3"),
                "pct_strain_heterogeneity": D("12.5"),
                "marker_lineage": "f__Enterobacteriaceae (UID5103)",
            },
            data={"bin": "260630_5158", "# genomes": "134", "5+": "41"},
        )
    )
    w.metrics(
        metrics_doc(s, "checkm2", {"pct_completeness": D("100.0"), "pct_contamination": D("112.5")})
    )
    w.metrics(
        metrics_doc(
            s,
            "mlst",
            {
                "scheme": "ecoli_achtman_4",
                "sequence_type": "11",
                "n_alleles_exact": 7,
                "n_alleles_novel": 0,
                "n_alleles_partial": 0,
                "n_alleles_missing": 0,
                "n_alleles_multiple": 0,
            },
            data={"file": "260630_5158.contigs.fa", "alleles": {}},
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "ectyper",
            {
                "serotype": "O157:H7",
                "o_antigen": "O157",
                "h_antigen": "H7",
                "species": "Escherichia coli",
                "qc": "PASS (REPORTABLE)",
                "n_genes": 3,
                "min_pct_identity": D("99.61"),
                "min_pct_coverage": D("100.0"),
            },
            data={"sample": "260630_5158", "genes": []},
        )
    )
    w.metrics(
        metrics_doc(
            s, "seqsero2", {}, status="skipped", messages=["SeqSero2 runs only for Salmonella"]
        )
    )
    d5158 = depth(427800000, 9822000)
    checks_5158 = [
        check(
            "species_match",
            "Escherichia coli (taxid 562)",
            None,
            {"expected_taxid": 562},
            "PASS",
            None,
        ),
        check("derived.depth", d5158, "x", {"min": 30, "warn_min": 35}, "PASS", None),
        check(
            "seqkit.n_contigs",
            1890,
            "contigs",
            {"max": 700, "warn_max": 550},
            "FAIL",
            "1890 > 700 (max)",
        ),
        check(
            "checkm2.pct_contamination",
            D("112.5"),
            "percent",
            {"max": 10, "warn_max": 5},
            "FAIL",
            "112.5 > 10 (max)",
        ),
    ]
    w.write(
        f"{s}.qc.json",
        qc_doc(
            s,
            "FAIL",
            w.files[s],
            checks_5158,
            species="Escherichia coli",
            taxid=562,
            profile="bacteria_wgs_outbreak",
            thresholds_sha=THRESHOLDS_V1,
            reasons=[
                "seqkit.n_contigs: 1890 > 700 (max)",
                "checkm2.pct_contamination: 112.5 > 10 (max)",
            ],
            unused=[],
        ),
    )
    w.write(
        f"{s}.report.json",
        report_doc(
            s,
            run_id,
            {"run_id": run_id, "client": "Laboratorium Przykładowe"},
            SPECIES_EC,
            sorted(w.files[s]),
        ),
    )

    # ---- 260630_5160: metrics only (pipeline stopped before qceval) -> incomplete, no verdict
    s = "260630_5160"
    w.metrics(
        metrics_doc(
            s,
            "fastp",
            fastp(402000, 391000, 121404000, 113390000, "86.0021", "88.0102", duplication="0.5011"),
        )
    )

    # ---- run.json and samplesheet
    from qcdb.summary_columns import summary_values  # same mapping as the database view

    def values_for(sample: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for name, _, _ in w.files.get(sample, {}).values():
            doc = json.loads((w.dir / name).read_text(), parse_float=Decimal)
            for k, m in doc["metrics"].items():
                metrics[f"{doc['source']['tool']}.{k}"] = m["value"]
        qc_path = w.dir / f"{sample}.qc.json"
        checks = (
            json.loads(qc_path.read_text(), parse_float=Decimal)["checks"]
            if qc_path.exists()
            else []
        )
        return {k: v for k, v in summary_values(metrics, checks).items() if v is not None}

    def entry(
        sample: str,
        verdict: str | None,
        species: str | None,
        st: str | None,
        serotype: str | None,
        amr: list[str] | None,
        points: list[str] | None,
        issues: list[str],
    ) -> dict[str, Any]:
        report = verdict is not None
        return {
            "sample_id": sample,
            "report": report,
            "verdict": verdict,
            "species": species,
            "mlst_st": st,
            "serotype": serotype,
            "n_amr_genes": len(amr) if amr is not None else None,
            "amr_genes": amr,
            "amr_point_mutations": points,
            "issues": issues,
            "values": values_for(sample) if report else {},
        }

    samples = [
        entry(
            "260630_5156",
            "PASS",
            "Salmonella enterica",
            "19",
            "Typhimurium",
            ["aph(3'')-Ib", "blaTEM-1", "sul2", "tet(B)"],
            ["gyrA_D87N"],
            [],
        ),
        entry(
            "260630_5157",
            "WARN",
            "Salmonella enterica",
            None,
            None,
            [],
            [],
            ["Q30 (surowe): WARN", "Liczba kontigów: WARN"],
        ),
        entry(
            "260630_5158",
            "FAIL",
            "Escherichia coli",
            "11",
            "O157:H7",
            None,
            None,
            ["Liczba kontigów: FAIL", "Zanieczyszczenie: FAIL"],
        ),
        entry("260630_5159", None, None, None, None, None, None, []),
        entry("260630_5160", None, None, None, None, None, None, []),
    ]
    run_doc = {
        "schema_version": "1.0",
        "run_id": run_id,
        "generator": {"name": "samplereport", "version": "1.0.0"},
        "summary": {"n_samples": 5, "PASS": 1, "WARN": 1, "FAIL": 1, "missing": 2},
        "columns": [
            {"id": i, "group": g, "label": lbl, "unit": u, "scale": sc}
            for i, g, lbl, u, sc in COLUMNS
        ],
        "samples": samples,
    }
    w.write(f"{run_id}.run.json", run_doc)
    sheet = ["sample,fastq_1,fastq_2,run_id"] + [
        f"{x},{x}_R1.fastq.gz,{x}_R2.fastq.gz,{run_id}"
        for x in ("260630_5156", "260630_5157", "260630_5158", "260630_5159", "260630_5160")
    ]
    (w.dir / "samplesheet.csv").write_text("\n".join(sheet) + "\n", encoding="utf-8")

    # ---- order document (created manually in the lab; kept in its own directory)
    order = dict(run_doc)
    order.pop("run_id")
    order.update(
        {
            "order_id": "ZL/2026/001",
            "meta": {"Zleceniodawca": "Jan Kowalski"},
            "runs": [run_id],
            "summary": {"n_samples": 2, "PASS": 1, "WARN": 1, "FAIL": 0, "missing": 0},
            "samples": [
                dict(x, run_id=run_id, client_report=f"{x['sample_id']}.html") for x in samples[:2]
            ],
        }
    )
    Writer(OUT / "orders").write("ZL_2026_001.order.json", order)


def build_run_2607() -> None:
    """Second run: 260630_5156 re-sequenced; run_id only from report.json; new thresholds."""
    w = Writer(OUT / "RUN_2607")
    run_id, s = "RUN_2607", "260630_5156"
    w.metrics(
        metrics_doc(
            s,
            "fastp",
            fastp(
                1610200, 1590100, 486280400, 462519000, "90.1234", "91.0021", duplication="0.6012"
            ),
        )
    )
    w.metrics(
        metrics_doc(
            s,
            "seqkit",
            {
                "n_contigs": 101,
                "total_length": 4951021,
                "largest_contig": 650021,
                "shortest_contig": 210,
                "mean_contig_length": D("49020.0099"),
                "n50": 210334,
                "l50": 9,
                "pct_gc": D("52.11"),
                "n_bases": 0,
                "n_per_100kbp": D("0.0"),
            },
            data={
                "file": "260630_5156.contigs.fa",
                "type": "DNA",
                "Q1": "900.0",
                "Q2": "4000.0",
                "Q3": "61000.0",
                "sum_gap": "0",
            },
        )
    )
    w.metrics(
        metrics_doc(s, "checkm2", {"pct_completeness": D("99.91"), "pct_contamination": D("0.21")})
    )
    w.metrics(
        metrics_doc(
            s,
            "mlst",
            {
                "scheme": "senterica_achtman_2",
                "sequence_type": "19",
                "n_alleles_exact": 7,
                "n_alleles_novel": 0,
                "n_alleles_partial": 0,
                "n_alleles_missing": 0,
                "n_alleles_multiple": 0,
            },
            data={"file": "260630_5156.contigs.fa", "alleles": {}},
        )
    )
    d = depth(462519000, 4951021)
    checks = [
        check(
            "species_match",
            "Salmonella enterica (taxid 28901)",
            None,
            {"expected_taxid": 28901},
            "PASS",
            None,
        ),
        check("derived.depth", d, "x", {"min": 40, "warn_min": 50}, "PASS", None),
        check("seqkit.n_contigs", 101, "contigs", {"max": 500, "warn_max": 300}, "PASS", None),
    ]
    w.write(
        f"{s}.qc.json",
        qc_doc(
            s,
            "PASS",
            w.files[s],
            checks,
            species="Salmonella enterica",
            taxid=28901,
            profile="bacteria_wgs",
            thresholds_sha=THRESHOLDS_V2,
            reasons=[],
            unused=[],
        ),
    )
    w.write(
        f"{s}.report.json",
        report_doc(s, run_id, {"run_id": run_id}, SPECIES_SE, sorted(w.files[s])),
    )


def build_metadata() -> None:
    directory = OUT / "metadata"
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        "sample_id,run_id,run_date,material_type,collection_site,collection_date,"
        "expected_species,order_id",
        "260630_5156,RUN_2606,2026-06-30,izolat,Zakład Przykładowy,2026-06-20,"
        "Salmonella enterica,ZL/2026/001",
        "260630_5158,RUN_2606,,izolat,,2026-06-22,Escherichia coli,ZL/2026/002",
    ]
    (directory / "metadata.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    build_run_2606()
    build_run_2607()
    build_metadata()


if __name__ == "__main__":
    main()
