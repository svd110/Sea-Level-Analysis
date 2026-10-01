"""Pure data transformations: raw API payloads -> tidy frames and indicators.

Nothing in this module touches the network, so everything here is covered by
unit tests with small hand-built inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .regions import coastal_region, ocean_basin

# NOAA's 2022 projections are referenced to mean sea level over 1991-2009
# (centred on 2000); observations are rebased to the same window so the two
# can share an axis.
BASELINE = (1991, 2009)
MIN_BASELINE_MONTHS = 120
KEY_YEARS = (2030, 2050, 2100)

# NOAA names some gauges after a landmark rather than the city people search for.
DISPLAY_NAMES = {
    "8723214": "Virginia Key (Miami)",
    "8518750": "The Battery (New York City)",
    "8761724": "Grand Isle (Louisiana)",
    "8638610": "Sewells Point (Norfolk)",
}

SCENARIOS = ["Low", "Intermediate-Low", "Intermediate", "Intermediate-High", "High"]
CORE_SCENARIOS = ["Low", "Intermediate", "High"]


# --- Station table -----------------------------------------------------------

def _year(date_str: str | None) -> float:
    if not date_str:
        return np.nan
    return float(date_str[-4:])


def _split_country(name: str, affil: str) -> tuple[str, str]:
    """"Reykjavik, Iceland" -> ("Reykjavik", "Iceland"); US names have no country."""
    if affil == "US":
        return name, "USA"
    place, _, country = name.rpartition(",")
    if not place:
        return name, ""
    return place.strip(), country.strip()


def direction(trend: float, ci: float) -> str:
    """Classify a trend by whether its 95% confidence interval excludes zero."""
    if trend - ci > 0:
        return "Rising"
    if trend + ci < 0:
        return "Falling"
    return "No clear trend"


def parse_trends(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        if r.get("trend") is None or r.get("latitude") is None:
            continue
        affil = r.get("affil") or ""
        station_id = str(r["stationId"])
        name = DISPLAY_NAMES.get(station_id, (r.get("stationName") or station_id).strip())
        place, country = _split_country(name, affil)
        lat, lon = float(r["latitude"]), float(r["longitude"])
        label = name if (affil != "US" or "," in name) else f"{name}, USA"
        rows.append({
            "station_id": station_id,
            "name": label,
            "place": place,
            "country": country,
            "affil": affil,
            "lat": lat,
            "lon": lon,
            "trend_mm_yr": float(r["trend"]),
            "trend_ci_mm_yr": float(r.get("trendError") or 0.0),
            "start_year": _year(r.get("startDate")),
            "end_year": _year(r.get("endDate")),
            "events": ", ".join(sorted({e["eventType"] for e in r.get("events") or []})),
            "basin": ocean_basin(lat, lon),
            "coastal_region": coastal_region(station_id, affil, country or place, lat, lon),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["record_years"] = df["end_year"] - df["start_year"]
    df["direction"] = [direction(t, c) for t, c in zip(df["trend_mm_yr"], df["trend_ci_mm_yr"])]
    return df


def build_station_table(us_records: list[dict], global_records: list[dict]) -> pd.DataFrame:
    df = pd.concat([parse_trends(us_records), parse_trends(global_records)], ignore_index=True)
    df = df.drop_duplicates("station_id").sort_values("name").reset_index(drop=True)
    return df


# --- Network and regional summaries -----------------------------------------

@dataclass
class NetworkStats:
    stations: int
    rising: int
    falling: int
    unclear: int
    median_trend: float


def network_stats(stations: pd.DataFrame) -> NetworkStats:
    counts = stations["direction"].value_counts()
    return NetworkStats(
        stations=len(stations),
        rising=int(counts.get("Rising", 0)),
        falling=int(counts.get("Falling", 0)),
        unclear=int(counts.get("No clear trend", 0)),
        median_trend=float(stations["trend_mm_yr"].median()),
    )


def region_summary(stations: pd.DataFrame, by: str, min_stations: int = 3) -> pd.DataFrame:
    """Median relative trend per region, with spread and share of rising gauges."""
    g = stations.groupby(by)["trend_mm_yr"]
    out = pd.DataFrame({
        "stations": g.size(),
        "median_mm_yr": g.median(),
        "q25_mm_yr": g.quantile(0.25),
        "q75_mm_yr": g.quantile(0.75),
        "rising_share": stations.assign(r=stations["direction"].eq("Rising")).groupby(by)["r"].mean(),
    })
    out = out[out["stations"] >= min_stations]
    return out.sort_values("median_mm_yr").reset_index(names="region")


# --- Station monthly series --------------------------------------------------

def parse_monthly(records: list[dict]) -> pd.DataFrame:
    rows = [{
        "date": pd.Timestamp(year=int(r["year"]), month=int(r["month"]), day=15),
        "msl_m": r.get("msl"),
        "msl_deseasoned_m": r.get("mslDeseasonalized"),
        "trend_m": r.get("trendLine"),
        "ci_high_m": r.get("upperConfidence"),
        "ci_low_m": r.get("lowerConfidence"),
    } for r in records]
    df = pd.DataFrame(rows, columns=["date", "msl_m", "msl_deseasoned_m",
                                     "trend_m", "ci_high_m", "ci_low_m"])
    return df.astype({c: float for c in df.columns if c != "date"}).sort_values("date")


def baseline_offset(monthly: pd.DataFrame) -> tuple[float, str]:
    """Mean sea level over the NOAA baseline window, falling back to the full record.

    Returns the offset in metres and a label describing the window used.
    """
    obs = monthly.dropna(subset=["msl_m"])
    years = obs["date"].dt.year
    window = obs[(years >= BASELINE[0]) & (years <= BASELINE[1])]
    if len(window) >= MIN_BASELINE_MONTHS:
        return float(window["msl_m"].mean()), f"{BASELINE[0]}–{BASELINE[1]} average"
    first, last = int(years.min()), int(years.max())
    return float(obs["msl_m"].mean()), f"{first}–{last} record average"


def to_cm(msl_m, offset_m: float):
    """Metres relative to station MSL -> cm relative to the baseline."""
    return (msl_m - offset_m) * 100


def annual_means(monthly: pd.DataFrame, min_months: int = 10) -> pd.DataFrame:
    """Calendar-year means, keeping only years with enough months observed."""
    obs = monthly.dropna(subset=["msl_m"])
    g = obs.groupby(obs["date"].dt.year)["msl_m"]
    out = pd.DataFrame({"msl_m": g.mean(), "months": g.size()})
    out = out[out["months"] >= min_months]
    return out.reset_index(names="year")


def observed_annual(annual: pd.DataFrame, offset_m: float, since: int = 1990) -> pd.DataFrame:
    """Annual means in cm on the baseline, for overlaying on projections."""
    out = pd.DataFrame({"year": annual["year"], "rsl_cm": to_cm(annual["msl_m"], offset_m)})
    return out[out["year"] >= since]


@dataclass
class Anomaly:
    value_cm: float
    baseline: str
    window: str  # e.g. "Sep 2025 – Aug 2026"


def current_anomaly(monthly: pd.DataFrame, months: int = 12) -> Anomaly | None:
    """Mean of the most recent 12 months relative to the baseline, in cm.

    Using a 12-month mean removes the seasonal cycle without needing a model.
    """
    obs = monthly.dropna(subset=["msl_m"])
    if obs.empty:
        return None
    offset, label = baseline_offset(obs)
    end = obs["date"].max()
    recent = obs[obs["date"] > end - pd.DateOffset(months=months)]
    if len(recent) < months // 2:
        return None
    window = f"{recent['date'].min():%b %Y} – {end:%b %Y}"
    return Anomaly((float(recent["msl_m"].mean()) - offset) * 100, label, window)


@dataclass
class Extreme:
    value_m: float
    month: str


def highest_recent(records: list[dict]) -> Extreme | None:
    """Highest monthly water level (m above station MSL) in the returned months."""
    best = None
    for r in records:
        try:
            v = float(r["highest"])
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or v > best[0]:
            best = (v, pd.Timestamp(year=int(r["year"]), month=int(r["month"]), day=1))
    if best is None:
        return None
    return Extreme(best[0], f"{best[1]:%b %Y}")


# --- Projections -------------------------------------------------------------

def parse_projections(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{
        "scenario": r["scenario"],
        "year": int(r["projectionYear"]),
        "rsl_cm": float(r["projectionRsl"]),
        "low_cm": float(r["projectionCiLow"]),
        "high_cm": float(r["projectionCiHigh"]),
    } for r in records if r.get("projectionRsl") is not None],
        columns=["scenario", "year", "rsl_cm", "low_cm", "high_cm"])
    df = df[df["scenario"].isin(SCENARIOS) & (df["year"] <= 2100)]
    df["scenario"] = pd.Categorical(df["scenario"], SCENARIOS, ordered=True)
    return df.sort_values(["scenario", "year"]).reset_index(drop=True)


def trend_anchor(annual: pd.DataFrame, offset_m: float, trend_mm_yr: float) -> tuple[int, float]:
    """Where the station's linear trend sits at its last observed year (cm vs baseline).

    The line has NOAA's slope and passes through the centroid of the annual
    means, which is exactly where an OLS fit with that slope would put it.
    """
    years = annual["year"].to_numpy(dtype=float)
    cm = to_cm(annual["msl_m"].to_numpy(), offset_m)
    last = int(years.max())
    return last, float(cm.mean() + trend_mm_yr * (last - years.mean()) / 10)


def extrapolate(trend_mm_yr: float, ci_mm_yr: float, start_year: int, start_cm: float,
                end_year: int = 2100) -> pd.DataFrame:
    """Continue the observed linear trend to ``end_year`` (cm on the station baseline).

    This is not a projection: it ignores the acceleration all scenarios include,
    so it is a lower-end reference, labelled as such in the app.
    """
    years = np.unique(np.append(np.arange(start_year, end_year + 1, 5), end_year))
    dt = years - start_year
    return pd.DataFrame({
        "year": years,
        "rsl_cm": start_cm + trend_mm_yr * dt / 10,
        "low_cm": start_cm + (trend_mm_yr - ci_mm_yr) * dt / 10,
        "high_cm": start_cm + (trend_mm_yr + ci_mm_yr) * dt / 10,
    })


def value_at(df: pd.DataFrame, year: int) -> float | None:
    """Linear interpolation of ``rsl_cm`` at ``year``, None outside the range."""
    if df.empty or not (df["year"].min() <= year <= df["year"].max()):
        return None
    return float(np.interp(year, df["year"], df["rsl_cm"]))


def projection_at(proj: pd.DataFrame, year: int, scenario: str | None = None) -> float | None:
    rows = proj[proj["year"] == year]
    if scenario is not None:
        rows = rows[rows["scenario"] == scenario]
    return float(rows["rsl_cm"].iloc[0]) if len(rows) else None


def scenario_range(proj: pd.DataFrame, year: int) -> tuple[float | None, float | None, float | None]:
    """(Low, Intermediate, High) projections at ``year``."""
    return tuple(projection_at(proj, year, s) for s in ("Low", "Intermediate", "High"))


# --- Global mean sea level ---------------------------------------------------

def parse_gmsl(rows: list[list[float]]) -> pd.DataFrame:
    """Satellite GMSL rebased to the 1993 mean, so values read as 'change since 1993'."""
    df = pd.DataFrame(rows, columns=["year", "gmsl_mm"]).astype(float).sort_values("year")
    base = df.loc[df["year"].between(1993, 1994, inclusive="left"), "gmsl_mm"]
    df["gmsl_mm"] -= base.mean() if len(base) else df["gmsl_mm"].iloc[0]
    df["date"] = pd.to_datetime(
        [f"{int(y)}-01-01" for y in df["year"]]
    ) + pd.to_timedelta((df["year"] % 1) * 365.25, unit="D")
    return df.reset_index(drop=True)


@dataclass
class GlobalTrend:
    rate_mm_yr: float
    recent_rate_mm_yr: float
    acceleration_mm_yr2: float
    start_year: int
    end_date: pd.Timestamp


def global_trend(gmsl: pd.DataFrame, recent_years: int = 10) -> GlobalTrend:
    t, y = gmsl["year"].to_numpy(), gmsl["gmsl_mm"].to_numpy()
    rate = np.polyfit(t, y, 1)[0]
    quad = np.polyfit(t - t.mean(), y, 2)[0]
    recent = t >= t.max() - recent_years
    recent_rate = np.polyfit(t[recent], y[recent], 1)[0]
    return GlobalTrend(float(rate), float(recent_rate), float(2 * quad),
                       int(t.min()), gmsl["date"].iloc[-1])
