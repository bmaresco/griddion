"""Local DuckDB cache. Everything downstream queries this file only."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "trivia.duckdb"


def connect(path: str | os.PathLike | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(path or os.environ.get("FT_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def run(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> None:
    """Execute a statement and drain its result (DuckDB 2.x requires this before the next call)."""
    con.execute(sql, params).fetchall()


def write_table(con: duckdb.DuckDBPyConnection, name: str, df: pl.DataFrame) -> None:
    con.register("_df", df.to_arrow())
    run(con, f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
    con.unregister("_df")


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchall()[0][0]
    )
