"""Refresh the bundled fallback snapshot in data/snapshot/.

The dashboard always tries the live APIs first; the snapshot is only used when
they are unreachable. Run this occasionally (or from CI) to keep it current:

    python scripts/refresh_snapshot.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from slr import sources  # noqa: E402


def main() -> None:
    for affil in ("US", "Global"):
        records = sources.fetch_trend_records(affil)
        sources.save_snapshot(f"trends_{affil.lower()}", records)
        print(f"trends_{affil.lower()}: {len(records)} stations")
    def report(origin: str, exc: sources.SourceError) -> None:
        print(f"gmsl: {origin} failed ({exc}), trying next provider")

    try:
        gmsl = sources.fetch_live(sources.GMSL_PROVIDERS, on_error=report)
    except sources.SourceError:
        print("gmsl: every provider failed; snapshot left unchanged")
        return
    sources.save_snapshot("gmsl", gmsl.data)
    print(f"gmsl: {len(gmsl.data)} rows from {gmsl.origin}")

if __name__ == "__main__":
    main()
