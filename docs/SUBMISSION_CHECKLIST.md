# POE-LMAPF Submission Checklist

Final, ordered list of everything the user needs to do **manually**
before paper resubmission.  Items are grouped by phase; each phase
gates the next.  Estimated wall-clock per item is in parentheses.

The complementary code-side checklist lives in
``docs/CONFORMANCE.md`` (already verified: 80 / 84 entries
**VERIFIED**, 3 **DEFERRED**, 1 **DRIFT**).  This file owns the
human-side actions that the artefact pipeline cannot perform on the
user's behalf.

---

## Phase 1 — Paper-text fill-ins (≈30 minutes)

- [ ] **§5.1 cluster spec** — replace the literal token
      ``[insert your cluster spec]`` with the run host details.  A
      drop-in template is in ``docs/PAPER_TODO.md`` §"§5.1 Cluster
      spec placeholder".  *(≈5 min once the numbers are in hand)*
- [ ] **§3.6 task arrival rate** — the paper currently defers to
      "Section 5.1".  Make the value concrete.  The simulator's auto
      formula is ``release_rate = H + W`` (map height + width) when
      ``task_arrival_rate`` is ``None`` (default).  Either quote that
      formula or fix a single number per map.  *(≈5 min)*
- [ ] **§4.3 N_max correction (DRIFT-1)** — the paper says
      $N_{\max} = 500$; the implementation uses 10 000.  Edit the
      paper's $N_{\max}$ token to ``10\,000`` (recommended) or change
      ``AStarLocalPlanner.MAX_EXPANSIONS`` to 500 in
      ``src/ha_lmapf/local_tier/local_planner.py``.  See
      ``docs/CONFORMANCE.md`` §"Local A\* expansion cap" for the
      rationale.  *(≈2 min)*
- [ ] **§4.3 Token Passing forward reference** — pick option A or
      option B from ``docs/PAPER_TODO.md`` §"§4.3 Hanging promise".
      Option A: run the
      ``configs/eval/paper/token_passing_ablation.yaml`` sweep and
      add a row to §5.5 with the new figure.  Option B: delete the
      §4.3 sentence "Token Passing is treated as an ablation in
      §5.5".  *(≈10 min for option B; ≈1–2 cluster-hours for option A
      sweep + ≈10 min text editing)*

---

## Phase 2 — Run the experiment matrix (cluster, ≈80–120 core-hours total)

Order chosen for diagnostic value vs. compute cost — see
``docs/REPRODUCING_PAPER.md`` §4 for the full rationale.

- [ ] **§5.5 baseline_comparison** (720 runs, ≈10–20 core-h).
      *Cheapest paper-figure sweep; validates Theorem 1 invariant
      on Ours and No-Buffer end-to-end.*
- [ ] **§5.3 fov_safety**            (400 runs, ≈4–8 core-h).
- [ ] **§5.4 scaling_agents**        (1040 runs, ≈20–40 core-h).
- [ ] **§5.4 scaling_exogenous**     (760 runs, ≈15–30 core-h).
- [ ] **§5.2 solver_sensitivity**    (3360 runs, ≈30–60 core-h).
- [ ] *(optional, response-letter material)* **aux_h_r_decoupling**
      (110 runs, ≈1 core-h).
- [ ] *(optional, if option A above)* **token_passing_ablation**
      (60 runs, ≈1–2 core-h).

The harness handles sharding, resume, and atomic CSV append; see
``docs/REPRODUCING_PAPER.md`` §2.

---

## Phase 3 — Generate paper artefacts (≈30 minutes wall-clock once Phase 2 finishes)

- [ ] **Plots** — ``scripts/evaluation/plot_paper_figures.py
      --figure all`` per sweep directory.  Output: 5 paper figures
      (Fig. 4–8) under ``figures/paper/``.
- [ ] **Tables** — ``scripts/evaluation/build_summary_tables.py
      --table all`` for each of the table-bearing sweeps.  Output:
      ``tables/paper/table1_solver_substitutability.{md,tex}`` and
      ``tables/paper/table2_baseline_comparison.{md,tex}``.
- [ ] **Statistical appendix** — runs automatically as part of the
      Phase-2 invocations whose YAMLs declare
      ``reference_condition``.  Outputs land in
      ``logs/paper/<sweep>/stats/``.
- [ ] **Claim validation** — ``scripts/evaluation/validate_paper_claims.py
      --claims docs/PAPER_NUMERICAL_CLAIMS.yaml --results-root
      logs/paper --out reports/claim_validation.md --tables-out
      reports/claim_validation_tables.tex``.

---

## Phase 4 — Update paper text from artefacts (≈2–3 hours)

- [ ] Read ``reports/claim_validation.md`` end-to-end.  For every
      **Refuted** entry, edit the corresponding sentence in §5.x to
      match the actual value.  The "Suggested replacement
      sentences" subsection has a drop-in candidate for each.
- [ ] For every **Now weaker** entry, soften the paper sentence.
      For every **Now stronger** entry, decide whether to claim
      more.
- [ ] **Replace Table 1** cells per the LaTeX in
      ``reports/claim_validation_tables.tex``.
- [ ] **Replace Table 2** cells the same way.
- [ ] **Replace Figures 4–8** with the new versions in
      ``figures/paper/``.
- [ ] Re-read §5.5 summary paragraph and rewrite every quoted
      number (10–30× lower than RHCR, 5–8× more violations under
      No-Buffer, etc.).  *Especially* the §5.5 final paragraph
      "10–30× lower than RHCR".
- [ ] Re-read §5.4 paragraphs containing "linearly" and confirm the
      R² values reported in the validation report agree.
- [ ] Re-read §5.2 throughput-range and planning-time claims;
      update if the actual numbers drifted.

---

## Phase 5 — Final paper read (≈1 hour)

- [ ] Re-read §1 contributions list (i)-(iv).  For each claim,
      verify the supporting experiment is in §5 and produces the
      claimed result in the new data.
- [ ] Re-read §3 (problem definition) and confirm the formal
      definitions match the implementation per
      ``docs/CONFORMANCE.md`` §3.
- [ ] Re-read §4 Algorithm 1 / Algorithm 2 / Theorem 1 against
      ``docs/CONFORMANCE.md`` §4.  In particular, verify the
      $N_{\max}$ token has been corrected (see Phase 1 DRIFT-1).
- [ ] Re-read §5.1 and confirm every default parameter is the one
      the harness actually used.

---

## Phase 6 — Reproducibility & submission (≈30 minutes)

- [ ] Re-run the validator one last time and confirm zero entries
      remain under **Refuted** or **Now weaker**.
- [ ] Re-run the test suite: ``pytest tests/ -q``.  Must finish
      with no failures (3 expected SKIPS for missing PIBT2 / RHCR
      binary builds; see ``docs/SOLVER_STATUS.md``).
- [ ] Run ``python scripts/lock_reproducibility.py`` one final
      time to refresh the snapshot in ``docs/reproducibility/``.
      Commit the resulting hashes.
- [ ] Record the final git commit hash; reference it in the
      paper's "code availability" footnote / supplementary
      material README.
- [ ] **Anonymise the GitHub URL** for double-blind submission.
      Replace any direct repo references in the paper with an
      anonymous placeholder ("a public repository [redacted for
      review]"); reveal in the camera-ready.
- [ ] Build the supplementary-material zip:
        ```
        figures/paper/*.{png,pdf}
        tables/paper/*.{md,tex}
        reports/claim_validation*.{md,tex}
        logs/paper/<sweep>/stats/*
        docs/CONFORMANCE.md
        docs/PAPER_TO_CODE_MAP.md
        docs/PAPER_NUMERICAL_CLAIMS.yaml
        docs/SOLVER_STATUS.md
        docs/reproducibility/*
        ```
- [ ] Submit.

---

## Estimated total user time (excluding Phase-2 cluster wall-clock)

| Phase                               | Estimate |
|-------------------------------------|----------|
| Phase 1 — paper-text fill-ins       | ≈30 min  |
| Phase 3 — generate artefacts        | ≈30 min  |
| Phase 4 — update paper text         | ≈2-3 h   |
| Phase 5 — final paper read          | ≈1 h     |
| Phase 6 — reproducibility & submit  | ≈30 min  |
| **Total active user time**          | **≈4–5 hours** |

Phase 2 is cluster wall-clock (≈80–120 core-hours), but is fully
automated and can run overnight.
