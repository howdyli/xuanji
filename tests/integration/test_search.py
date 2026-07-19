#!/usr/bin/env python3
"""Quick test script for SearchService.

Usage:
    python tests/integration/test_search.py "搜索关键词"
    python tests/integration/test_search.py "航班查询" --routing-key user123
    python tests/integration/test_search.py "PDF" --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv(override=True)


async def run(query: str, routing_key: str | None, limit: int) -> None:
    from xiaopaw.config.validator import load_config
    from xiaopaw.frontend.search_service import SearchService
    from pathlib import Path

    cfg = load_config(Path(os.environ.get("XIAOPAW_CONFIG", "config.yaml")))
    pg_dsn = cfg.memory.db_dsn
    if not pg_dsn:
        print("ERROR: memory.db_dsn not configured in config.yaml")
        sys.exit(1)

    svc = SearchService(pg_dsn=pg_dsn)
    print(f"SearchService created, pg_dsn={pg_dsn[:40]}...")
    print(f"Query: {query!r}, routing_key={routing_key}, limit={limit}\n")

    results = await svc.search(query=query, routing_key=routing_key, limit=limit)

    print(f"Results: {len(results)} session(s)\n")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] session_id : {r['session_id']}")
        print(f"      title      : {r['title'][:80]}")
        print(f"      match_count: {r['match_count']}")
        print(f"      max_score  : {r['max_score']}")
        print(f"      created_at : {r['created_at']}")
        print()

    # Also dump raw JSON
    print("--- JSON ---")
    print(json.dumps(results, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SearchService")
    parser.add_argument("query", help="Search keywords")
    parser.add_argument("--routing-key", default=None, help="Filter by routing key")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    args = parser.parse_args()

    asyncio.run(run(args.query, args.routing_key, args.limit))


if __name__ == "__main__":
    main()
