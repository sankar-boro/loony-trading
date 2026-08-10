#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fetch_instruments.sh — Download the live Upstox instrument master as .xlsx
#
# The auto-download in data_engine/upstox/instruments.py currently 403s
# because it points at a dead URL (assets.upstox.com/market-assets/...).
# The live, working path is assets.upstox.com/market-quote/instruments/...
# This script downloads that file, extracts it, and converts it to an Excel
# sheet you can open directly, e.g. to check whether a hardcoded
# instrument_key in KNOWN_INSTRUMENTS is stale.
#
# Requires: python3 with pandas + openpyxl (pip install pandas openpyxl)
#
# Usage:
#   bash scripts/fetch_instruments.sh          # NSE -> data/instruments/NSE.xlsx
#   bash scripts/fetch_instruments.sh BSE      # download BSE instead
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${BOT_DIR}/data/instruments"
mkdir -p "${OUT_DIR}"

EXCHANGE="${1:-NSE}"
URL="https://assets.upstox.com/market-quote/instruments/exchange/${EXCHANGE}.csv.gz"
GZ_FILE="${OUT_DIR}/${EXCHANGE}.csv.gz"
CSV_FILE="${OUT_DIR}/${EXCHANGE}.csv"
XLSX_FILE="${OUT_DIR}/${EXCHANGE}.xlsx"

echo "Downloading: ${URL}"
curl -sL -f -o "${GZ_FILE}" "${URL}" || {
    echo "Download failed (HTTP error) for ${URL}" >&2
    exit 1
}

echo "Extracting: ${GZ_FILE} -> ${CSV_FILE}"
gunzip -kf "${GZ_FILE}"

echo "Converting to Excel: ${CSV_FILE} -> ${XLSX_FILE}"
python3 - "${CSV_FILE}" "${XLSX_FILE}" <<'PY'
import sys
import pandas as pd

csv_path, xlsx_path = sys.argv[1], sys.argv[2]
df = pd.read_csv(csv_path, dtype=str)
df.to_excel(xlsx_path, index=False, sheet_name="instruments")
print(f"Wrote {len(df):,} rows to {xlsx_path}")
PY

echo
echo "Done: ${XLSX_FILE}"
