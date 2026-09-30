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
    for origin, fetch in sources.GMSL_PROVIDERS:
        try:
            rows = fetch()
        except sources.SourceError as exc:
            print(f"gmsl: {origin} failed ({exc}), trying next provider")
            continue
        sources.save_snapshot("gmsl", rows)
        print(f"gmsl: {len(rows)} rows from {origin}")
        break


if __name__ == "__main__":
    main()
