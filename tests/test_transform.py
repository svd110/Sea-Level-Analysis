import numpy as np
import pandas as pd
import pytest

from slr import transform as T


def trend_record(**overrides):
    base = {
        "stationId": "8723214", "stationName": "Virginia Key", "affil": "US",
        "latitude": 25.73, "longitude": -80.16, "trend": 3.2, "trendError": 0.11,
        "startDate": "06/15/1931", "endDate": "12/15/2025", "events": [],
    }
    return {**base, **overrides}


def monthly_records(start_year, end_year, rate_mm_yr=3.0, offset_m=0.0):
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            t = y + (m - 0.5) / 12
            out.append({"year": y, "month": m, "msl": offset_m + rate_mm_yr * (t - 2000) / 1000,
                        "mslDeseasonalized": None, "trendLine": None,
                        "upperConfidence": None, "lowerConfidence": None})
    return out


# --- station table -----------------------------------------------------------

def test_parse_trends_us_station_gets_display_name_and_regions():
    df = T.parse_trends([trend_record()])
    row = df.iloc[0]
    assert row["name"] == "Virginia Key (Miami), USA"
    assert row["country"] == "USA"
    assert row["basin"] == "Atlantic"
    assert row["coastal_region"] == "US East Coast"
    assert row["record_years"] == 94
    assert row["direction"] == "Rising"


def test_parse_trends_splits_country_from_global_name():
    df = T.parse_trends([trend_record(stationId="010-001", stationName="Reykjavik, Iceland",
                                      affil="Global", latitude=64.15, longitude=-21.93)])
    assert df.iloc[0]["place"] == "Reykjavik"
    assert df.iloc[0]["country"] == "Iceland"


def test_parse_trends_skips_records_without_a_trend():
    assert T.parse_trends([trend_record(trend=None)]).empty


def test_parse_trends_flags_events():
    df = T.parse_trends([trend_record(events=[{"eventType": "Earthquake"}])])
    assert df.iloc[0]["events"] == "Earthquake"


@pytest.mark.parametrize("trend, ci, expected", [
    (3.0, 0.5, "Rising"),
    (-3.0, 0.5, "Falling"),
    (0.3, 0.5, "No clear trend"),
])
def test_direction_uses_confidence_interval(trend, ci, expected):
    assert T.direction(trend, ci) == expected


def test_region_summary_drops_small_groups_and_sorts():
    stations = pd.DataFrame({
        "basin": ["A"] * 3 + ["B"] * 3 + ["C"],
        "trend_mm_yr": [1, 2, 3, -1, -2, -3, 9],
        "direction": ["Rising"] * 3 + ["Falling"] * 3 + ["Rising"],
    })
    out = T.region_summary(stations, "basin")
    assert list(out["region"]) == ["B", "A"]
    assert out.set_index("region").loc["A", "median_mm_yr"] == 2
    assert out.set_index("region").loc["B", "rising_share"] == 0


# --- monthly series ----------------------------------------------------------

def test_baseline_uses_1991_2009_when_available():
    monthly = T.parse_monthly(monthly_records(1980, 2020, offset_m=1.0))
    offset, label = T.baseline_offset(monthly)
    assert label == "1991–2009 average"
    # The window's midpoint is 2000.5, half a year above the series' zero crossing.
    assert offset == pytest.approx(1.0 + 0.0015, abs=1e-6)


def test_baseline_falls_back_to_record_mean():
    monthly = T.parse_monthly(monthly_records(2010, 2020))
    _, label = T.baseline_offset(monthly)
    assert label == "2010–2020 record average"


def test_current_anomaly_matches_linear_rise():
    monthly = T.parse_monthly(monthly_records(1980, 2020, rate_mm_yr=3.0))
    a = T.current_anomaly(monthly)
    # 2020's midpoint is 20 years after the baseline midpoint (2000.5): 20 * 3 mm = 6 cm.
    assert a.value_cm == pytest.approx(6.0, abs=0.01)
    assert a.window == "Jan 2020 – Dec 2020"


def test_current_anomaly_none_without_data():
    assert T.current_anomaly(T.parse_monthly([])) is None


def test_annual_means_require_enough_months():
    recs = monthly_records(2000, 2001)[:18]  # 2001 has only six months
    annual = T.annual_means(T.parse_monthly(recs))
    assert list(annual["year"]) == [2000]


def test_highest_recent_picks_max_and_skips_bad_rows():
    recs = [{"year": "2026", "month": "7", "highest": "0.6"},
            {"year": "2026", "month": "8", "highest": "0.9"},
            {"year": "2026", "month": "9", "highest": None}]
    e = T.highest_recent(recs)
    assert e.value_m == 0.9 and e.month == "Aug 2026"
    assert T.highest_recent([]) is None


# --- projections -------------------------------------------------------------

def test_parse_projections_orders_scenarios_and_caps_at_2100():
    recs = [{"scenario": s, "projectionYear": y, "projectionRsl": v,
             "projectionCiLow": v - 1, "projectionCiHigh": v + 1}
            for s, v in [("High", 40), ("Low", 20), ("Intermediate", 30)]
            for y in (2050, 2100, 2150)]
    df = T.parse_projections(recs)
    assert df["year"].max() == 2100
    assert list(df.loc[df["year"] == 2050, "scenario"]) == ["Low", "Intermediate", "High"]
    assert T.projection_at(df, 2050, "Intermediate") == 30
    assert T.projection_at(df, 2030, "Intermediate") is None


def test_trend_anchor_and_extrapolation():
    monthly = T.parse_monthly(monthly_records(1991, 2009, rate_mm_yr=4.0))
    annual = T.annual_means(monthly)
    offset, _ = T.baseline_offset(monthly)
    year, cm = T.trend_anchor(annual, offset, 4.0)
    assert year == 2009
    assert cm == pytest.approx(0.4 * 9, abs=0.05)  # 9 years after the 2000 centre
    ex = T.extrapolate(4.0, 1.0, year, cm)
    assert ex["year"].iloc[0] == 2009 and ex["year"].iloc[-1] == 2100
    assert T.value_at(ex, 2100) == pytest.approx(cm + 0.4 * 91)
    assert (ex["low_cm"] <= ex["rsl_cm"]).all() and (ex["rsl_cm"] <= ex["high_cm"]).all()
    assert T.value_at(ex, 1990) is None


# --- global mean sea level ---------------------------------------------------

def test_global_trend_recovers_rate_and_acceleration():
    t = np.arange(1993, 2026, 0.1)
    y = 3.0 * (t - 1993) + 0.05 * (t - 1993) ** 2  # acceleration = 0.1 mm/yr^2
    g = T.parse_gmsl(np.column_stack([t, y]).tolist())
    assert g.loc[g["year"] < 1994, "gmsl_mm"].mean() == pytest.approx(0)  # rebased to 1993
    gt = T.global_trend(g)
    assert gt.acceleration_mm_yr2 == pytest.approx(0.1, rel=1e-3)
    assert gt.recent_rate_mm_yr > gt.rate_mm_yr
