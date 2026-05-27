# Anytime semantics: algorithm class vs harness behavior

Six paper-sweep solvers, classified by published algorithm class and observed harness behavior in this calibration run.

| Solver | Algorithm class | Harness behavior | Reason | §5.1 "partial solutions are still used" applies? |
|---|---|---|---|---|
| cbsh2 | optimal CBS (no anytime; complete-or-timeout) | Algorithmically anytime, complete-or-error in harness | optimal CBS — complete-or-timeout by design | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |
| lacam3 | anytime (search-based, refines until budget) | Algorithmically anytime, complete-or-error in harness | writes its result file even on partial returns | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |
| lacam_official | anytime (search-based, refines until budget) | Algorithmically anytime, complete-or-error in harness | writes its result file even on partial returns | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |
| lns2 | anytime (LNS; writes paths only at end-of-run) | Algorithmically anytime, complete-or-error in harness | writes the paths file only at end-of-run; no partial output to recover | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |
| pbs | suboptimal incomplete (no anytime; no parking-room handling) | Algorithmically anytime, complete-or-error in harness | priority-based; complete-or-incomplete by design | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |
| pibt2 | non-anytime (priority-based; sub-millisecond typical) | Algorithmically anytime, complete-or-error in harness | priority-scheme returns first feasible plan; no anytime iteration | Indirectly — the binary self-terminates at `-t` with the best plan it found (status = complete) or no plan at all (status = error/timeout_no_result) |

## Implication for §5.1

The §5.1 claim "partial solutions returned by anytime solvers are still used" applies cleanly to **LaCAM\*** and **LaCAM** (the `partial_anytime` status fires in this calibration), and indirectly to **MAPF-LNS2** (the binary's anytime iteration is real but its all-or-nothing paths-file write means partial returns manifest as either `complete` with the best plan it had at budget, or `error` with no plan at all — never `partial_anytime`).

For **PIBT2**, **CBSH2-RTC**, and **PBS**, the §5.1 anytime claim does not directly apply.  These are non-anytime solvers; their harness behavior is binary (complete or error).

