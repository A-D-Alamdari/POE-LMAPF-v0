All calibration data here was produced with task_allocator=greedy.

This is the v1.4 reference data captured before the Direction A
activation (commit d802864, "DIRECTION A ACTIVATION: replace greedy
with conflict_aware").

The decomposition_summary.md in this directory reports the headline
ratios computed against greedy:
  §5.4 allocator-vs-exogenous ratio: 24.0×
  §5.5 allocator-vs-exogenous ratio: 19.3×

The live logs/calibration/*.csv files at the parent directory will
be overwritten when the calibration is re-run with conflict_aware.
This archive is the only record of the pre-Direction-A state.

Archive created: 2026-05-13 (locally; the activation commit landed
2026-05-11). logs/ is gitignored, so this archive lives only on
this machine.
