# Checklist: validating qcdb against real run directories

Everything in this repository has been verified only against **fixtures generated from the
brief** (`fixtures/`). The real `qcmetrics`/`qceval`/`samplereport` outputs were never available.
Work through this list on a copy of the database before production use.

## Before loading

- [ ] Pick 3+ historical run directories covering different years, tool versions and
      species (at least one E. coli and one Salmonella run).
- [ ] Make sure the directories contain `*.run.json` or a `samplesheet*.csv/tsv`, so every
      sample has a run_id.
- [ ] `qcdb load <dir> --dry-run` for each: note every `REJECT`, `UNREADABLE` and `WARN` line.

## Rejections

- [ ] `not in the metric dictionary`: a real metric missing from the brief's dictionary.
      Add it to `backend/src/qcdb/data/metric_dictionary.psv` and run `qcdb import-dictionary`.
      Never relax validation instead.
- [ ] `is not of dictionary type int`: a whole number is accepted (`252.0`); a fractional value
      for an `int` metric means the dictionary type is wrong (as with `fastp.insert_size_peak`,
      decision D4). Discuss before widening.
- [ ] `unit ... does not match`: report to the qcmetrics maintainers; units are a contract.
- [ ] `conflicting run_id` / `cannot determine run_id`: check report.json, run.json and the
      samplesheet for the sample.
- [ ] `unsupported schema_version`: a 2.x document. Do not load it; qcdb needs an update.
- [ ] report/run/order outline errors: a field qcdb reads has a different shape in real files.

## Warnings that confirm the design

- [ ] `run.json <column>=... but documents give ...` must be **zero**. This confirms the
      summary-column mapping D3 (seqkit vs QUAST, CheckM2 vs CheckM, `×2` reads, depth from
      `derived.depth`). Any difference means the mapping must change (one migration).
- [ ] `sha256 of input ... does not match` must be zero for untouched directories. Otherwise
      qc.json hashes something other than the file bytes; report it.
- [ ] `run.json verdict ... but qc.json verdict ...` must be zero.
- [ ] `summary differs from the database` must be zero (`missing` = samples without a verdict).
- [ ] `file name does not match its content`: sample IDs containing dots or renamed files.
- [ ] `biological samples share this code`: expected only for IDs like `S01`; link in the UI.

## After loading

- [ ] Load the same directory twice: the second run reports `new versions 0`.
- [ ] Re-run qceval on one sample, load again: a new version, old verdict still in history.
- [ ] Spot-check 5 samples in SQL: verdict and checks equal `qc.json`, metrics equal
      `*.metrics.json` (absent metrics have no row, `null` metrics have a row without a value).
- [ ] A sample sequenced in two runs gives two results linked to one biological sample.
- [ ] Tools with `empty`, `skipped`, `failed` and `missing` statuses are all present.
- [ ] `checkm*.pct_contamination` above 100 is loaded unchanged.
- [ ] `amr_hit` and `species_abundance` contain the expected genes and species.
- [ ] Load an `*.order.json`: orders are created without an owner; samples are linked.
- [ ] Run the module in the pipeline with `-stub`, then for real; check `qcdb_load.log`.
