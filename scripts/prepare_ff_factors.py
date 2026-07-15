"""Parse and merge Ken French daily factor files.

The raw files from the Data Library have a copyright/description header of varying
length, a blank line, then the data, then a trailing copyright line. The momentum file
also has trailing commas on every row (it is a 3-column CSV with an empty third column).

Both are published in PERCENT. `data.load_ff_factors()` divides by 100, so this script
writes raw percent values and does NOT pre-divide. Getting this wrong silently scales
every regression coefficient by 100 and is exactly the kind of error that produces a
plausible-looking table.

Output: data/raw/ff_factors_daily.csv with columns Mkt-RF, SMB, HML, RMW, CMA, UMD, RF.

Run:  PYTHONPATH=src python3 scripts/prepare_ff_factors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
FIVE_FACTOR = RAW / "F-F_Research_Data_5_Factors_2x3_daily.csv"
MOMENTUM = RAW / "F-F_Momentum_Factor_daily.csv"
OUT = RAW / "ff_factors_daily.csv"


def find_header_row(path: Path, first_col_name: str) -> int:
    """Locate the data header line.

    The header is the line beginning with a comma (empty date column name) followed by
    the first factor name. Searching for it rather than hard-coding a skiprows count
    matters: the header length differs between the two files (4 lines vs 13), and French
    changes it periodically.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        for i, line in enumerate(f):
            if line.strip().startswith(f",{first_col_name}"):
                return i
    raise ValueError(f"Could not find header row starting ',{first_col_name}' in {path}")


def load_ff_file(path: Path, first_col_name: str) -> pd.DataFrame:
    """Read one Ken French daily CSV, returning a date-indexed frame of percent values."""
    header_row = find_header_row(path, first_col_name)

    df = pd.read_csv(
        path,
        skiprows=header_row,
        index_col=0,
        encoding="utf-8-sig",
    )

    # Drop the trailing copyright line and any blank rows: keep only 8-digit YYYYMMDD
    # indices. The annual-data section that some French files carry uses 4-digit years,
    # so this filter removes it too.
    idx = pd.Series(df.index.astype(str)).str.strip()
    is_daily = idx.str.fullmatch(r"\d{8}").to_numpy()
    df = df[is_daily]

    df.index = pd.to_datetime(idx[is_daily].to_numpy(), format="%Y%m%d")
    df.index.name = "Date"

    # The momentum file has a trailing empty column from its trailing commas.
    keep = [c for c in df.columns if str(c).strip() not in ("", "Unnamed: 2")]
    df = df[keep]
    df = df.dropna(axis=1, how="all")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.apply(pd.to_numeric, errors="coerce")

    # French marks missing data as -99.99 or -999.
    df = df.mask((df <= -99.99) | (df <= -999))

    return df


def main() -> int:
    for p in (FIVE_FACTOR, MOMENTUM):
        if not p.exists():
            print(f"ERROR: {p} not found.", file=sys.stderr)
            print(
                "Download from the Ken French Data Library:\n"
                "  - Fama/French 5 Factors (2x3) [Daily]\n"
                "  - Momentum Factor (Mom) [Daily]\n"
                f"and unzip into {RAW}/",
                file=sys.stderr,
            )
            return 1

    five = load_ff_file(FIVE_FACTOR, "Mkt-RF")
    mom = load_ff_file(MOMENTUM, "Mom")

    print(f"5-factor: {five.shape[0]} rows, {five.index.min().date()} to {five.index.max().date()}")
    print(f"          columns: {list(five.columns)}")
    print(f"momentum: {mom.shape[0]} rows, {mom.index.min().date()} to {mom.index.max().date()}")
    print(f"          columns: {list(mom.columns)}")

    # Inner join: only dates present in both. An outer join would introduce NaN rows that
    # a regression would silently drop anyway, but less visibly.
    merged = five.join(mom, how="inner")
    merged = merged.rename(columns={"Mom": "UMD"})

    expected = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "UMD", "RF"]
    missing = set(expected) - set(merged.columns)
    if missing:
        print(f"ERROR: missing expected columns after merge: {missing}", file=sys.stderr)
        print(f"       got: {list(merged.columns)}", file=sys.stderr)
        return 1

    merged = merged[expected]
    merged = merged.dropna()

    merged.to_csv(OUT)

    print(f"\nWrote {OUT}")
    print(f"  {merged.shape[0]} rows x {merged.shape[1]} columns")
    print(f"  {merged.index.min().date()} to {merged.index.max().date()}")
    print("\n  NOTE: values are in PERCENT. data.load_ff_factors() divides by 100.")
    print("\nFirst 3 rows:")
    print(merged.head(3).to_string())
    print("\nLast 3 rows:")
    print(merged.tail(3).to_string())
    print("\nSanity check -- annualised mean (%):")
    print((merged.mean() * 252).round(2).to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
