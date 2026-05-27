# POE-LMAPF Reproducibility Manifest

Snapshots the artefacts a third party needs to verify they are reproducing **the same release** as the paper-attached supplementary material.  Re-run ``scripts/lock_reproducibility.py --check-only`` to verify no hashes have drifted since this manifest was generated.

- generated: ``2026-05-17T07:43:30.524012Z``
- git commit: ``f119f58ee368b5b097e32d56f18a5dcf7ea102d3``
- working tree clean: ``False``
- Python: ``3.10.20``
- platform: ``Linux-6.17.0-23-generic-x86_64-with-glibc2.39``

## Artefact files

- [`environment.txt`](environment.txt) — git commit, Python version, ``pip freeze``.
- [`config_hashes.txt`](config_hashes.txt) — SHA-256 of every YAML under ``configs/``.
- [`results_hashes.txt`](results_hashes.txt) — SHA-256 of every ``logs/**/results.csv``.

## Verification recipe

```bash
git checkout f119f58ee368b5b097e32d56f18a5dcf7ea102d3
pip install -r requirements.txt
pip install -e .
python scripts/lock_reproducibility.py --check-only
```

If ``--check-only`` exits ``0``, the artefacts on disk match the snapshot recorded here.  Any non-zero exit indicates drift between the recorded hashes and the current files; the script prints the diverging paths.
