"""Network access to NOAA CO-OPS and satellite-altimetry data.

Every function here does I/O only: it fetches, lightly unwraps the payload and
returns plain Python / pandas objects. Parsing and analysis live in
``transform.py`` so they can be unit-tested without the network.

Loaders that feed the whole dashboard (station trends, global mean sea level)
fall back to a bundled snapshot in ``data/snapshot`` when the live request
fails, so the app still renders if NOAA or CU Boulder is down. The returned
``Fetched`` records whether the data is live or from the snapshot, which drives
the status indicator in the header.
"""

from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

DPAPI = "https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/product"
DATAGETTER = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
CU_HOME = "https://sealevel.colorado.edu/"
STAR_GMSL = (
    "https://www.star.nesdis.noaa.gov/socd/lsa/SeaLevelRise/slr/"
    "slr_sla_gbl_free_ref_90.csv"
)

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshot"
TIMEOUT = 45
RETRY_STATUS = {429, 500, 502, 503, 504}
HEADERS = {"User-Agent": "sea-level-analytics-dashboard (educational project)"}


class SourceError(RuntimeError):
    """A data source could not be reached or returned unusable content."""


@dataclass
class Fetched:
    data: Any
    fetched_at: datetime
    source: str  # "live" or "snapshot"
    origin: str  # human-readable provider name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get(url: str, params: dict | None = None, attempts: int = 3) -> requests.Response:
    """GET with retries on timeouts and gateway errors (NOAA returns 504s under load)."""
    error = ""
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
        except (requests.Timeout, requests.ConnectionError) as exc:
            error = str(exc)
        except requests.RequestException as exc:
            raise SourceError(f"{url}: {exc}") from exc
        else:
            if resp.status_code == 200:
                return resp
            error = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUS:
                break
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"{url}: {error}")


def _get_json(url: str, params: dict | None = None, attempts: int = 3) -> dict:
    resp = _get(url, params, attempts)
    try:
        return resp.json()
    except ValueError as exc:
        raise SourceError(f"{url}: response was not JSON") from exc


def _snapshot_path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.json"


def save_snapshot(name: str, payload: Any) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    body = {"saved_at": _now().isoformat(), "payload": payload}
    _snapshot_path(name).write_text(json.dumps(body))


def _load_snapshot(name: str) -> tuple[Any, datetime]:
    path = _snapshot_path(name)
    if not path.exists():
        raise SourceError(f"no snapshot for {name}")
    body = json.loads(path.read_text())
    return body["payload"], datetime.fromisoformat(body["saved_at"])


def _with_snapshot(name: str, origin: str, fetch: Callable[[], Any]) -> Fetched:
    try:
        return Fetched(fetch(), _now(), "live", origin)
    except SourceError:
        payload, saved_at = _load_snapshot(name)
        return Fetched(payload, saved_at, "snapshot", origin)


# --- Station trends ---------------------------------------------------------

def fetch_trend_records(affil: str) -> list[dict]:
    """Long-term relative sea-level trends; affil is "US" or "Global"."""
    body = _get_json(f"{DPAPI}/sealvltrends.json", {"affil": affil, "units": "metric"})
    records = body.get("SeaLvlTrends")
    if not records:
        raise SourceError(f"sealvltrends affil={affil}: empty response")
    return records


def load_trends(affil: str) -> Fetched:
    return _with_snapshot(
        f"trends_{affil.lower()}", "NOAA CO-OPS Sea Level Trends",
        lambda: fetch_trend_records(affil),
    )


def fetch_monthly_means(station_id: str) -> list[dict]:
    """Monthly mean sea level (m, relative to station MSL) with NOAA's trend line."""
    body = _get_json(
        f"{DPAPI}/sealvltrends.json",
        {"station": station_id, "details": "monthlymeans",
         "units": "metric", "trendType": "SINGLE"},
    )
    return body.get("data") or []


# --- Projections (NOAA 2022 Interagency Technical Report, US only) ----------

def _projection_query(params: dict) -> list[dict]:
    # A miss comes back as HTTP 500, so don't retry.
    try:
        body = _get_json(f"{DPAPI}/slr_projections.json", {**params, "units": "metric"}, attempts=1)
    except SourceError:
        return []
    return body.get("SlrProjections") or []


def fetch_projection_records(station_id: str, lat: float, lon: float) -> tuple[list[dict], str]:
    """Find projections for a US station.

    NOAA indexes projections by tide-gauge ID, by the gauge's exact coordinates,
    or on a 1-degree grid. Station IDs in the trends product don't always match
    the projections product (e.g. Miami Beach), so try each in turn and report
    which one matched.
    """
    records = _projection_query({"station": station_id})
    if records:
        return records, "tide gauge"
    records = _projection_query({"lat": lat, "lon": lon})
    if records:
        return records, "tide gauge (matched by location)"
    # Nearest 1-degree grid cell, then its neighbours, closest first.
    base_lat, base_lon = round(lat), round(lon)
    cells = sorted(
        ((base_lat + dy, base_lon + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)),
        key=lambda c: (c[0] - lat) ** 2 + (c[1] - lon) ** 2,
    )
    for cell_lat, cell_lon in cells:
        records = _projection_query({"lat": cell_lat, "lon": cell_lon})
        if records:
            return records, f"1° grid cell {cell_lat}°, {cell_lon}°"
    return [], ""


# --- Live water levels (US CO-OPS stations only) ----------------------------

def fetch_latest_water_level(station_id: str) -> dict | None:
    """Most recent 6-minute observation relative to station MSL, or None."""
    try:
        body = _get_json(DATAGETTER, {
            "date": "latest", "station": station_id, "product": "water_level",
            "datum": "MSL", "units": "metric", "time_zone": "gmt", "format": "json",
        })
    except SourceError:
        return None
    data = body.get("data")
    return data[0] if data else None


def fetch_recent_monthly_extremes(station_id: str, months: int = 12) -> list[dict]:
    """Monthly highest water level (and MSL) for the last ``months`` months."""
    end = _now()
    start = (pd.Timestamp(end) - pd.DateOffset(months=months)).to_pydatetime()
    try:
        body = _get_json(DATAGETTER, {
            "begin_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"),
            "station": station_id, "product": "monthly_mean", "datum": "MSL",
            "units": "metric", "time_zone": "gmt", "format": "json",
        })
    except SourceError:
        return []
    return body.get("data") or []


# --- Global mean sea level from satellite altimetry -------------------------

def _fetch_cu_gmsl() -> list[list[float]]:
    """CU Boulder GMSL, seasonal signal and GIA removed (mm).

    The file name changes with every release, so discover it from the home page.
    """
    home = _get(CU_HOME).text
    links = re.findall(r"https://sealevel\.colorado\.edu/files/[^\"']*seasons_rmvd\.txt", home)
    if not links:
        raise SourceError("CU Boulder: GMSL file link not found")
    text = _get(links[0]).text
    df = pd.read_csv(io.StringIO(text), comment="#", sep=r"\s+", header=None,
                     names=["year", "gmsl_mm"])
    if df.empty:
        raise SourceError("CU Boulder: empty GMSL file")
    return df.dropna().values.tolist()


def _fetch_star_gmsl() -> list[list[float]]:
    """NOAA STAR GMSL; one column per altimetry mission, merged into one series."""
    text = _get(STAR_GMSL).text
    df = pd.read_csv(io.StringIO(text), comment="#")
    series = df.drop(columns="year").bfill(axis=1).iloc[:, 0]
    out = pd.DataFrame({"year": df["year"], "gmsl_mm": series}).dropna()
    if out.empty:
        raise SourceError("NOAA STAR: empty GMSL file")
    return out.values.tolist()


GMSL_PROVIDERS = (
    ("CU Boulder Sea Level Research Group", _fetch_cu_gmsl),
    ("NOAA Laboratory for Satellite Altimetry", _fetch_star_gmsl),
)


def load_gmsl() -> Fetched:
    for origin, fetch in GMSL_PROVIDERS:
        try:
            return Fetched(fetch(), _now(), "live", origin)
        except SourceError:
            continue
    payload, saved_at = _load_snapshot("gmsl")
    return Fetched(payload, saved_at, "snapshot", GMSL_PROVIDERS[0][0])
