"""Global Sea Level Analytics — Streamlit dashboard.

How is sea level changing at different coastal locations, and what does the
current trend imply for future coastal conditions?

Run with:  streamlit run app.py
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from slr import charts, sources
from slr import transform as T
from slr.theme import get_theme

st.set_page_config(page_title="Global Sea Level Analytics", page_icon="🌊", layout="wide")

DEFAULT_STATION = "8723214"  # Virginia Key, Miami
NETWORK_TTL = 60 * 60  # station trends and satellite GMSL: hourly
LIVE_TTL = 6 * 60  # water levels update every 6 minutes
PROJECTION_TTL = 24 * 60 * 60  # projections are static (2022 report)
DATASETS = {
    "All stations": None,
    "US (NOAA CO-OPS)": "US",
    "International (PSMSL)": "Global",
}
GROUPINGS = {"Ocean basin": "basin", "Coastal region": "coastal_region"}


# --- Cached loaders ----------------------------------------------------------

@st.cache_data(ttl=NETWORK_TTL, show_spinner="Loading station trends from NOAA…")
def load_network() -> tuple[pd.DataFrame, list[sources.Fetched]]:
    us, gl = sources.load_trends("US"), sources.load_trends("Global")
    table = T.build_station_table(us.data, gl.data)
    # Drop the payloads from the metadata we keep around.
    meta = [replace(f, data=None) for f in (us, gl)]
    return table, meta


@st.cache_data(ttl=NETWORK_TTL, show_spinner="Loading satellite sea-level record…")
def load_gmsl() -> tuple[pd.DataFrame, sources.Fetched]:
    f = sources.load_gmsl()
    return T.parse_gmsl(f.data), replace(f, data=None)


@st.cache_data(ttl=NETWORK_TTL, show_spinner=False)
def load_monthly(station_id: str) -> pd.DataFrame:
    return T.parse_monthly(sources.fetch_monthly_means(station_id))


@st.cache_data(ttl=PROJECTION_TTL, show_spinner=False)
def load_projections(station_id: str, lat: float, lon: float) -> tuple[pd.DataFrame, str]:
    records, matched = sources.fetch_projection_records(station_id, lat, lon)
    return T.parse_projections(records), matched


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def load_live(station_id: str) -> tuple[dict | None, T.Extreme | None, datetime]:
    latest = sources.fetch_latest_water_level(station_id)
    extreme = T.highest_recent(sources.fetch_recent_monthly_extremes(station_id))
    return latest, extreme, datetime.now(timezone.utc)


# --- Styling -----------------------------------------------------------------

ctx_theme = getattr(st.context, "theme", None)
theme = get_theme(getattr(ctx_theme, "type", None))

st.markdown(f"""
<style>
/* Clear Streamlit's fixed toolbar (3.75rem) so the title isn't clipped. */
.block-container {{ padding-top: 4.75rem; max-width: 1400px; }}
.slr-header {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-end;
  gap:.75rem 2rem; border-bottom:1px solid {theme.grid}; padding-bottom:.9rem; margin-bottom:1rem; }}
.slr-header h1 {{ font-size:1.75rem; margin:0; padding:0; line-height:1.2; }}
.slr-header p {{ margin:.25rem 0 0; color:{theme.ink_secondary}; font-size:.95rem; }}
.slr-status {{ display:flex; gap:1rem; align-items:center; color:{theme.ink_secondary};
  font-size:.85rem; white-space:nowrap; }}
.slr-pill {{ display:inline-flex; align-items:center; gap:.4rem; padding:.2rem .65rem;
  border-radius:999px; border:1px solid {theme.grid}; font-weight:600; color:{theme.ink}; }}
.slr-dot {{ width:.55rem; height:.55rem; border-radius:50%; display:inline-block; }}
.slr-facts {{ display:grid; grid-template-columns:auto 1fr; gap:.35rem 1rem; font-size:.9rem;
  margin:.25rem 0 .75rem; }}
.slr-facts dt {{ color:{theme.ink_secondary}; }}
.slr-facts dd {{ margin:0; font-variant-numeric: tabular-nums; }}
.slr-note {{ color:{theme.ink_muted}; font-size:.8rem; }}
.slr-station-name {{ font-size:1.3rem; font-weight:650; margin:0; }}
</style>
""", unsafe_allow_html=True)


def metric(col, label, value, note=None, **kwargs):
    """A bordered KPI card; ``note`` is shown as a neutral caption under the value."""
    if note is not None:
        kwargs.update(delta=note, delta_color="off", delta_arrow="off")
    return col.metric(label, value, border=True, **kwargs)


def plot(fig, **kwargs):
    return st.plotly_chart(fig, theme=None, width="stretch",
                           config={"displaylogo": False}, **kwargs)


# --- Data --------------------------------------------------------------------

try:
    stations_all, network_meta = load_network()
except sources.SourceError:
    st.error("Station trends are unavailable: NOAA did not respond and no snapshot is bundled. "
             "Try again in a few minutes.")
    st.stop()

try:
    gmsl, gmsl_meta = load_gmsl()
except sources.SourceError:
    gmsl, gmsl_meta = None, None

all_meta = network_meta + ([gmsl_meta] if gmsl_meta else [])
is_live = gmsl_meta is not None and all(m.source == "live" for m in all_meta)
updated = min(m.fetched_at for m in all_meta)

# --- Header ------------------------------------------------------------------

status_color, status_label = (theme.good, "LIVE") if is_live else (theme.warning, "SNAPSHOT")
st.markdown(f"""
<div class="slr-header">
  <div>
    <h1>🌊 Global Sea Level Analytics</h1>
    <p>How is sea level changing along the world's coasts, and what does the current trend
    imply for the future?</p>
  </div>
  <div class="slr-status">
    <span>Last updated {updated:%d %b %Y, %H:%M} UTC</span>
    <span class="slr-pill" title="{'All sources fetched live' if is_live else 'One or more sources unavailable; showing the bundled snapshot'}">
      <span class="slr-dot" style="background:{status_color}"></span>{status_label}</span>
  </div>
</div>
""", unsafe_allow_html=True)
if not is_live:
    st.warning("Some data sources could not be reached, so part of the dashboard is showing "
               "the bundled snapshot. The status returns to LIVE once they respond.", icon="⚠️")

# --- Selection state ---------------------------------------------------------

if "station_id" not in st.session_state:
    st.session_state.station_id = DEFAULT_STATION


def _map_pick() -> str | None:
    """Station id from the latest map click, if the click is new."""
    event = st.session_state.get("station_map")
    points = (event or {}).get("selection", {}).get("points", []) if event else []
    if not points:
        return None
    cd = points[0].get("customdata")
    sid = str(cd[0]) if cd else None
    if sid is None or sid == st.session_state.get("_last_map_pick"):
        return None
    st.session_state._last_map_pick = sid
    return sid


picked = _map_pick()
if picked:
    st.session_state.station_id = picked
    st.session_state.station_pick = picked


def _on_search():
    st.session_state.station_id = st.session_state.station_pick


# --- Controls (one row, above the content they filter) -----------------------

c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="bottom")
names = dict(zip(stations_all["station_id"], stations_all["name"]))
if st.session_state.station_id not in names:
    st.session_state.station_id = DEFAULT_STATION
st.session_state.setdefault("station_pick", st.session_state.station_id)
c1.selectbox("Find a station", options=list(names), format_func=names.get,
             key="station_pick", on_change=_on_search,
             help="Type to search, or click a station on the map.")
dataset = c2.selectbox("Stations shown", list(DATASETS))
if c3.button("Refresh data", help="Fetch fresh data now instead of waiting for the hourly refresh"):
    st.cache_data.clear()
    st.rerun()

affil = DATASETS[dataset]
stations = stations_all if affil is None else stations_all[stations_all["affil"] == affil]
stations = stations.reset_index(drop=True)
station = stations_all.set_index("station_id").loc[st.session_state.station_id]
sid = st.session_state.station_id
is_us = station["affil"] == "US"

# --- Station data ------------------------------------------------------------

try:
    monthly = load_monthly(sid)
except sources.SourceError:
    monthly = T.parse_monthly([])
has_monthly = monthly["msl_m"].notna().any()
if has_monthly:
    offset_m, baseline_label = T.baseline_offset(monthly)
    annual = T.annual_means(monthly)
    anomaly = T.current_anomaly(monthly)
else:
    offset_m, baseline_label, annual, anomaly = 0.0, "", pd.DataFrame(), None

proj, proj_match = (load_projections(sid, float(station["lat"]), float(station["lon"]))
                    if is_us else (pd.DataFrame(), ""))
has_proj = len(proj) > 0

extrap = None
if not has_proj and has_monthly and len(annual):
    start_year, start_cm = T.trend_anchor(annual, offset_m, station["trend_mm_yr"])
    extrap = T.extrapolate(station["trend_mm_yr"], station["trend_ci_mm_yr"], start_year, start_cm)

latest, extreme, live_at = load_live(sid) if is_us else (None, None, None)

# --- KPI row -----------------------------------------------------------------

k1, k2, k3, k4 = st.columns(4)
if gmsl is not None:
    gt = T.global_trend(gmsl)
    metric(
        k1, "Global trend (satellites)", f"{gt.rate_mm_yr:+.1f} mm/yr",
        f"{gt.recent_rate_mm_yr:+.1f} mm/yr over the last decade",
        chart_data=gmsl.groupby(gmsl["year"].astype(int))["gmsl_mm"].mean().round(1).tolist(),
        chart_type="area",
        help=(f"Global mean sea level from satellite altimetry, {gt.start_year + 1}–"
              f"{gt.end_date:%Y}. The rise is accelerating by about "
              f"{gt.acceleration_mm_yr2:.2f} mm/yr each year. Source: {gmsl_meta.origin}."),
    )
else:
    metric(k1, "Global trend (satellites)", "—", help="Satellite record unavailable.")

metric(
    k2, "Selected station trend", f"{station['trend_mm_yr']:+.2f} mm/yr",
    f"± {station['trend_ci_mm_yr']:.2f} mm/yr (95% confidence)",
    help=("Long-term relative sea-level trend: includes both ocean rise and vertical "
          "land motion (sinking land adds to it, rising land subtracts)."),
)
arrow = {"Rising": "↑", "Falling": "↓"}.get(station["direction"], "→")
metric(
    k3, "Trend direction", f"{arrow} {station['direction']}", station["name"],
    help="Rising/falling only when the 95% confidence interval excludes zero.",
)
if has_proj:
    lo, mid, hi = T.scenario_range(proj, 2050)
    metric(k4, "Projection 2050 (Intermediate)", f"{mid:+.0f} cm",
           f"Low–High range: {lo:+.0f} to {hi:+.0f} cm",
           help="NOAA 2022 Interagency scenarios, relative to the 2000 baseline "
                "(1991–2009 average).")
elif extrap is not None:
    v = T.value_at(extrap, 2050)
    metric(k4, "2050 if the trend continues", f"{v:+.0f} cm", "Linear extrapolation only",
           help=f"Straight-line continuation of the observed trend, vs the {baseline_label}. "
                "NOAA scenarios cover US stations only; this ignores acceleration and "
                "likely understates future rise.")
else:
    metric(k4, "Projection 2050", "—", help="No projection available.")

# --- Map + station panel -----------------------------------------------------

map_col, panel_col = st.columns([2.2, 1], gap="large")
with map_col:
    st.markdown("##### Station trends")
    st.caption("Each dot is a tide gauge coloured by its long-term trend: red = sea level rising "
               "relative to the land, blue = falling (usually because the land is rising). "
               "Click a station to explore it.")
    plot(charts.station_map(stations, theme, sid), key="station_map",
         on_select="rerun", selection_mode="points")

with panel_col:
    st.markdown(f'<p class="slr-station-name">{station["name"]}</p>', unsafe_allow_html=True)
    facts = [
        ("Current trend", f"{station['trend_mm_yr']:+.2f} ± {station['trend_ci_mm_yr']:.2f} mm/yr"),
        ("Observation period", f"{int(station['start_year'])}–{int(station['end_year'])} "
                               f"({int(station['record_years'])} yrs)"),
    ]
    if anomaly:
        facts.append(("Latest anomaly", f"{anomaly.value_cm:+.1f} cm vs {anomaly.baseline}"))
    if latest:
        facts.append(("Latest water level", f"{float(latest['v']):+.2f} m vs MSL "
                                            f"({latest['t'][11:]} UTC)"))
    if extreme:
        facts.append(("Highest, last 12 months", f"{extreme.value_m:+.2f} m vs MSL ({extreme.month})"))
    facts.append(("Ocean basin", station["basin"]))
    facts.append(("Coastal region", station["coastal_region"]))
    facts.append(("Network", "NOAA CO-OPS" if is_us else "PSMSL (via NOAA)"))
    st.markdown('<dl class="slr-facts">' + "".join(
        f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>", unsafe_allow_html=True)
    if anomaly:
        st.caption(f"Latest anomaly = mean of {anomaly.window}; a 12-month mean removes the seasonal cycle.")
    if station["events"]:
        st.caption(f"⚠️ NOAA flags this record: {station['events']}. The trend may be affected.")

    st.markdown("**Projected rise**")
    if has_proj:
        rows = [{"Year": str(y), "Intermediate": f"{mid:+.0f} cm",
                 "Low – High": f"{lo:+.0f} to {hi:+.0f} cm"}
                for y in T.KEY_YEARS for lo, mid, hi in [T.scenario_range(proj, y)]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"NOAA 2022 scenarios ({proj_match}), relative to the 2000 baseline.")
    elif extrap is not None:
        rows = [{"Year": str(y), "Trend continued": f"{v:+.0f} cm"}
                for y in T.KEY_YEARS if (v := T.value_at(extrap, y)) is not None]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Linear extrapolation of the observed trend, vs the "
                   f"{baseline_label}. Not a climate projection.")
    else:
        st.caption("No projection available for this station.")

# --- Station charts ----------------------------------------------------------

h_col, p_col = st.columns(2, gap="large")
with h_col:
    st.markdown(f"##### Historical sea level · {station['place']}")
    if has_monthly:
        plot(charts.station_history(monthly, annual, offset_m, theme, baseline_label))
        st.caption("Relative sea level measured by the tide gauge. The dashed line is NOAA's "
                   "fitted linear trend.")
    else:
        st.info("Monthly data for this station could not be loaded right now.")

with p_col:
    head, toggle = st.columns([3, 2], vertical_alignment="bottom")
    head.markdown("##### Looking ahead" if has_proj else "##### If the trend continues")
    # Scenarios exist only for US stations; elsewhere there is nothing to toggle.
    show_all = has_proj and toggle.toggle(
        "Show all 5 scenarios", value=False,
        help="NOAA publishes five scenarios; the default view shows Low, Intermediate and High.")
    observed = T.observed_annual(annual, offset_m) if has_monthly and len(annual) else None
    y_title = "cm vs 2000 baseline" if has_proj else f"cm vs {baseline_label}"
    if has_proj or extrap is not None:
        plot(charts.station_projection(proj if has_proj else None, extrap, observed,
                                       theme, show_all, y_title))
    if has_proj:
        st.caption("Scenarios range from Low (today's rate roughly continues) to High "
                   "(rapid ice-sheet loss). Blue dots are observations on a comparable "
                   "baseline, so you can see which path the station is tracking.")
    elif extrap is not None:
        st.caption("NOAA's scenarios cover US stations only. This straight-line continuation "
                   "ignores the acceleration seen globally, so treat it as a lower-end "
                   "reference, not a forecast.")
    else:
        st.info("Not enough data to extend the trend for this station.")

# --- Global context ----------------------------------------------------------

st.divider()
# Headings share a row so both charts start at the same height, whatever the toggle adds.
g_head, r_head = st.columns(2, gap="large", vertical_alignment="center")
g_head.markdown("##### Global sea level over time")
with r_head:
    h_col, t_col = st.columns([3, 2], vertical_alignment="center")
    grouping = t_col.segmented_control("Group regions by", list(GROUPINGS), default="Ocean basin",
                                       label_visibility="collapsed") or "Ocean basin"
    h_col.markdown(f"##### Trend by {grouping.lower()}")

g_col, r_col = st.columns(2, gap="large")
with g_col:
    if gmsl is not None:
        plot(charts.gmsl_chart(gmsl, theme))
        st.caption(f"Global mean sea level from satellite altimetry ({gmsl_meta.origin}), "
                   "seasonal cycle removed. The upward curve of the fit shows the rise "
                   "is speeding up.")
    else:
        st.info("The satellite record could not be loaded right now.")

with r_col:
    summary = T.region_summary(stations, GROUPINGS[grouping])
    plot(charts.region_bars(summary, theme))
    st.caption("Bars show the median station trend; whiskers show the middle half of "
               "stations. Regions where the land is still rebounding from Ice Age glaciers "
               "(the Baltic, Alaska, the Arctic) show falling relative sea level.")

ns = T.network_stats(stations)
s1, s2, s3, s4 = st.columns(4)  # height="stretch" keeps the cards level


def share(n: int) -> str | None:
    return f"{n / ns.stations:.0%} of stations" if ns.stations else None


metric(s1, "Monitored stations", f"{ns.stations}", height="stretch",
       help=f"Tide gauges with a long-term NOAA trend ({dataset.lower()}).")
metric(s2, "↑ Significantly rising", f"{ns.rising}", share(ns.rising), height="stretch")
metric(s3, "↓ Significantly falling", f"{ns.falling}", share(ns.falling), height="stretch")
metric(s4, "Median station trend", f"{ns.median_trend:+.2f} mm/yr", height="stretch",
       help="Relative trends at gauges, so it differs from the satellite global mean.")

# --- Methods and data --------------------------------------------------------

with st.expander("Methodology and data sources"):
    st.markdown(f"""
**Station trends.** NOAA CO-OPS [Sea Level Trends](https://tidesandcurrents.noaa.gov/sltrends/)
product: linear trends fitted to monthly mean sea level after removing the seasonal cycle, with
95% confidence intervals that account for serial correlation. International stations come from
the Permanent Service for Mean Sea Level (PSMSL) and are processed the same way by NOAA. These are
*relative* trends: they combine ocean rise with vertical land motion, which is what matters for
coastal flooding.

**Global trend.** Satellite altimetry (TOPEX/Poseidon, Jason 1–3, Sentinel-6), from
{gmsl_meta.origin if gmsl_meta else "CU Boulder / NOAA LSA"}. Rate = least-squares slope;
acceleration = twice the quadratic coefficient.

**Projections.** NOAA 2022 *Global and Regional Sea Level Rise Scenarios for the United States*
(Sweet et al.), relative to a 2000 baseline (1991–2009 average). A station without its own
projection uses the tide gauge at the same location or the nearest 1° grid cell. Outside the US,
the dashboard shows a straight-line continuation of the observed trend instead, which ignores
acceleration.

**Latest anomaly.** Mean of the latest 12 monthly values minus the 1991–2009 average (or the
full-record average if the station lacks enough data in that window).

**Regions.** Ocean basins and coastal regions are assigned by rule from coordinates and country,
an approximation for aggregation only.

**Refresh.** Station trends and the satellite record are cached for one hour; live water levels
for six minutes. If a source is unreachable the dashboard falls back to a bundled snapshot and
the status shows SNAPSHOT.
""")

with st.expander("Station data table"):
    table = stations[["name", "trend_mm_yr", "trend_ci_mm_yr", "direction", "start_year",
                      "end_year", "basin", "coastal_region", "lat", "lon"]]
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "name": "Station",
        "trend_mm_yr": st.column_config.NumberColumn("Trend (mm/yr)", format="%+.2f"),
        "trend_ci_mm_yr": st.column_config.NumberColumn("± 95% CI", format="%.2f"),
        "direction": "Direction",
        "start_year": st.column_config.NumberColumn("From", format="%d"),
        "end_year": st.column_config.NumberColumn("To", format="%d"),
        "basin": "Ocean basin",
        "coastal_region": "Coastal region",
        "lat": st.column_config.NumberColumn("Lat", format="%.2f"),
        "lon": st.column_config.NumberColumn("Lon", format="%.2f"),
    })
    st.download_button("Download CSV", table.to_csv(index=False), "sea_level_trends.csv",
                       "text/csv")

st.caption("Data: NOAA CO-OPS, PSMSL, CU Boulder Sea Level Research Group, NOAA Laboratory for "
           "Satellite Altimetry. Altimetry data are provided by NOAA Laboratory for Satellite "
           "Altimetry.")
