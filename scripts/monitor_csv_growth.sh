#!/bin/bash
# Row-count growth monitor for long-running sweep CSVs.
#
# Stop condition: when "${csv}.monitor" sentinel file is removed.
# Stall alert: emits "STALLED" if no new rows in ${alert_after} seconds
# (default 30 min) — investigate, do not panic; some warehouse high-
# density cells genuinely consume the full 10 s budget per call.
#
# Usage:
#   touch logs/paper/<sweep>/results.csv.monitor
#   bash scripts/monitor_csv_growth.sh logs/paper/<sweep>/results.csv 1800 &
#   ...run sweep...
#   rm logs/paper/<sweep>/results.csv.monitor
set -u
csv="${1:?csv path required}"
alert_after="${2:-1800}"
last_rows=0
last_change=$(date +%s)
while [ -f "${csv}.monitor" ]; do
    rows=$(wc -l < "$csv" 2>/dev/null)
    rows=${rows:-0}
    now=$(date +%s)
    if [ "$rows" -gt "$last_rows" ]; then
        last_rows=$rows
        last_change=$now
    fi
    elapsed=$((now - last_change))
    if [ "$elapsed" -gt "$alert_after" ]; then
        echo "$(date '+%H:%M:%S'): STALLED — no growth in ${elapsed}s (current: $rows rows)"
    else
        echo "$(date '+%H:%M:%S'): $rows rows (last change ${elapsed}s ago)"
    fi
    sleep 60
done
