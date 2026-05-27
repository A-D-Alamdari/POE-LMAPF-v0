#!/usr/bin/env bash
# Download the three MovingAI MAPF maps used in the paper Section 5.2
# sweep.  Idempotent — skips files that already exist with the expected
# dimensions.  Run from the repo root:
#
#     bash scripts/download_maps.sh
#
# Network errors on individual files are reported but do not abort the
# script; rerun once your connection is available again.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAPS_DIR="${REPO_ROOT}/data/maps"
mkdir -p "${MAPS_DIR}"

# (filename, URL, expected_width, expected_height)
declare -a MAPS=(
  "random-64-64-10.map        https://movingai.com/benchmarks/random/random-64-64-10.map               64  64"
  "warehouse-10-20-10-2-1.map https://movingai.com/benchmarks/warehouse/warehouse-10-20-10-2-1.map     161 63"
  "warehouse-10-20-10-2-2.map https://movingai.com/benchmarks/warehouse/warehouse-10-20-10-2-2.map     170 84"
)

fetch() {
  local url="$1" out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --connect-timeout 10 -o "${out}.partial" "${url}" \
      && mv "${out}.partial" "${out}"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --tries=3 --timeout=10 -O "${out}.partial" "${url}" \
      && mv "${out}.partial" "${out}"
  else
    echo "ERROR: neither curl nor wget is available" >&2
    return 1
  fi
}

verify() {
  local file="$1" exp_w="$2" exp_h="$3"
  local h w
  h="$(awk '/^height/ {print $2; exit}' "$file" 2>/dev/null)"
  w="$(awk '/^width/  {print $2; exit}' "$file" 2>/dev/null)"
  [[ "$h" == "$exp_h" && "$w" == "$exp_w" ]]
}

for entry in "${MAPS[@]}"; do
  read -r filename url exp_w exp_h <<<"$entry"
  out="${MAPS_DIR}/${filename}"
  if [[ -f "$out" ]] && verify "$out" "$exp_w" "$exp_h"; then
    echo "[skip] ${filename} already present (${exp_w}x${exp_h})"
    continue
  fi
  echo "[fetch] ${filename}  <-  ${url}"
  if fetch "$url" "$out"; then
    if verify "$out" "$exp_w" "$exp_h"; then
      echo "[ok]    ${filename} (${exp_w}x${exp_h})"
    else
      echo "[warn]  ${filename} downloaded but dimensions did not match ${exp_w}x${exp_h}"
    fi
  else
    echo "[fail]  ${filename}  (network error; retry later)"
  fi
done
