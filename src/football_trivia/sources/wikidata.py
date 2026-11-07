"""Wikidata crosswalk: Pro Football Reference ID -> enwiki article title (+ DOB)."""

from __future__ import annotations

import io

import polars as pl

from ..db import write_table
from ..http import get

SPARQL = """
SELECT ?item ?pfr ?title ?dob WHERE {
  ?item wdt:P3561 ?pfr .
  OPTIONAL { ?item wdt:P569 ?dob }
  OPTIONAL { ?art schema:about ?item ;
                  schema:isPartOf <https://en.wikipedia.org/> ;
                  schema:name ?title }
}
"""


def refresh(con, log=print) -> None:
    log("wikidata: PFR id -> Wikipedia title crosswalk")
    r = get(
        "https://query.wikidata.org/sparql",
        params={"query": SPARQL},
        headers={"Accept": "text/csv"},
    )
    df = pl.read_csv(io.StringIO(r.text), infer_schema=False)
    df = (
        df.with_columns(
            qid=pl.col("item").str.extract(r"(Q\d+)$"),
            # Wikidata stores "F/FostDe00"; nflverse uses "FostDe00"
            pfr_id=pl.col("pfr").str.split("/").list.last(),
            birth_date=pl.col("dob").str.slice(0, 10),
        )
        .select("qid", "pfr_id", "title", "birth_date")
        .unique(subset=["qid", "pfr_id"], keep="first")
    )
    write_table(con, "raw_wikidata", df)
    log(f"  {df.height} rows, {df['title'].is_not_null().sum()} with enwiki titles")
