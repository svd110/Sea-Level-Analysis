"""Plotly figure builders. Each takes tidy frames from ``transform`` and a Theme."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .theme import Theme, rgba
from .transform import CORE_SCENARIOS, KEY_YEARS, SCENARIOS, to_cm

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
TREND_RANGE = 8  # mm/yr; map colours saturate beyond +/- this


def _base_layout(theme: Theme, height: int, **extra) -> dict:
    axis = dict(gridcolor=theme.grid, linecolor=theme.axis, zeroline=False, automargin=True,
                tickfont=dict(color=theme.ink_muted, size=11),
                title_font=dict(color=theme.ink_secondary, size=12))
    layout = dict(
        height=height,
        paper_bgcolor=theme.surface,
        plot_bgcolor=theme.surface,
        font=dict(family=FONT, color=theme.ink, size=12),
        margin=dict(l=64, r=12, t=40, b=48),
        xaxis=dict(axis),
        yaxis=dict(axis),
        hoverlabel=dict(bgcolor=theme.surface, bordercolor=theme.axis,
                        font=dict(family=FONT, color=theme.ink)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(color=theme.ink_secondary, size=11), bgcolor="rgba(0,0,0,0)"),
    )
    layout.update(extra)
    return layout


def _band(fig: go.Figure, x, low, high, color: str, theme: Theme, name: str) -> None:
    """Shaded range between ``low`` and ``high`` (an invisible upper edge, then fill)."""
    fig.add_trace(go.Scatter(x=x, y=high, mode="lines", line=dict(width=0),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=x, y=low, mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor=rgba(color, theme.band_alpha), name=name, hoverinfo="skip",
    ))


# --- Map ---------------------------------------------------------------------

def station_map(stations: pd.DataFrame, theme: Theme, selected_id: str | None) -> go.Figure:
    n = len(theme.diverging) - 1
    colorscale = [[i / n, c] for i, c in enumerate(theme.diverging)]
    period = [f"{int(s)}–{int(e)}" for s, e in zip(stations["start_year"], stations["end_year"])]
    half = TREND_RANGE // 2
    custom = np.stack([
        stations["station_id"], stations["name"], stations["trend_mm_yr"],
        stations["trend_ci_mm_yr"], period, stations["direction"],
    ], axis=-1)

    fig = go.Figure()
    sel = stations[stations["station_id"] == selected_id]
    if len(sel):
        # Halo under the selected station (map markers have no outline property).
        fig.add_trace(go.Scattermap(
            lat=sel["lat"], lon=sel["lon"], mode="markers", hoverinfo="skip",
            marker=dict(size=22, color=theme.ink, opacity=0.9), showlegend=False,
            customdata=custom[sel.index],
        ))
    fig.add_trace(go.Scattermap(
        lat=stations["lat"], lon=stations["lon"], mode="markers",
        customdata=custom,
        marker=dict(
            size=10, color=stations["trend_mm_yr"].clip(-TREND_RANGE, TREND_RANGE),
            colorscale=colorscale, cmin=-TREND_RANGE, cmax=TREND_RANGE,
            colorbar=dict(
                title=dict(text="Trend<br>mm/yr", font=dict(color=theme.ink_secondary, size=11)),
                tickvals=[-TREND_RANGE, -half, 0, half, TREND_RANGE],
                ticktext=[f"≤ −{TREND_RANGE}", f"−{half}", "0", f"+{half}", f"≥ +{TREND_RANGE}"],
                tickfont=dict(color=theme.ink_muted, size=11),
                thickness=10, len=0.6, x=0.99, xanchor="right", bgcolor=rgba(theme.surface, 0.85),
                outlinewidth=0,
            ),
        ),
        # Selection only drives the station panel; don't fade the other stations.
        selected=dict(marker=dict(opacity=1)),
        unselected=dict(marker=dict(opacity=1)),
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>"
            "Trend: %{customdata[2]:+.2f} ± %{customdata[3]:.2f} mm/yr<br>"
            "%{customdata[5]} · %{customdata[4]}<extra></extra>"
        ),
        showlegend=False,
    ))
    fig.update_layout(
        **_base_layout(theme, 520, margin=dict(l=0, r=0, t=0, b=0)),
        map=dict(style=theme.map_style, center=dict(lat=22, lon=10), zoom=0.55),
        uirevision="station-map",  # keep the user's pan/zoom across reruns
        clickmode="event+select",
    )
    return fig


# --- Station history ---------------------------------------------------------

def station_history(monthly: pd.DataFrame, annual: pd.DataFrame, offset_m: float,
                    theme: Theme, baseline: str) -> go.Figure:
    fig = go.Figure()
    obs = monthly.dropna(subset=["msl_m"])
    fig.add_trace(go.Scatter(
        x=obs["date"], y=to_cm(obs["msl_m"], offset_m), name="Monthly mean",
        mode="lines", line=dict(color=theme.series_soft, width=1),
        hovertemplate="%{x|%b %Y}: %{y:+.1f} cm<extra>Monthly</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(annual["year"].astype(str) + "-07-01"),
        y=to_cm(annual["msl_m"], offset_m), name="Annual mean",
        mode="lines", line=dict(color=theme.series, width=2),
        hovertemplate="%{x|%Y}: %{y:+.1f} cm<extra>Annual</extra>",
    ))
    trend = monthly.dropna(subset=["trend_m"])
    if len(trend):
        fig.add_trace(go.Scatter(
            x=trend["date"], y=to_cm(trend["trend_m"], offset_m), name="Linear trend (NOAA)",
            mode="lines", line=dict(color=theme.reference, width=1.5, dash="dash"),
            hoverinfo="skip",
        ))
    fig.update_layout(**_base_layout(theme, 320, hovermode="x unified"))
    fig.update_yaxes(title_text=f"cm vs {baseline}")
    fig.add_hline(y=0, line=dict(color=theme.axis, width=1))
    return fig


# --- Projections -------------------------------------------------------------

def _scenario_color(theme: Theme, scenario: str) -> str:
    return theme.scenario[SCENARIOS.index(scenario)]


def station_projection(proj: pd.DataFrame | None, extrap: pd.DataFrame | None,
                       observed: pd.DataFrame | None, theme: Theme, show_all: bool,
                       y_title: str) -> go.Figure:
    """NOAA scenarios (US) or a labelled linear extrapolation (elsewhere).

    ``observed`` is annual means already in cm on the same baseline, drawn as
    dots so the reader can see whether observations track the scenarios.
    """
    fig = go.Figure()
    end_labels = []

    if proj is not None and len(proj):
        wide = proj.pivot(index="year", columns="scenario", values="rsl_cm")
        years = wide.index
        if not show_all:
            _band(fig, years, wide["Low"], wide["High"], _scenario_color(theme, "Intermediate"),
                  theme, "Low–High range")
        for scenario in (SCENARIOS if show_all else CORE_SCENARIOS):
            core = scenario == "Intermediate"
            fig.add_trace(go.Scatter(
                x=years, y=wide[scenario], name=scenario, legendrank=SCENARIOS.index(scenario),
                mode="lines+markers" if core else "lines",
                line=dict(color=_scenario_color(theme, scenario), width=2.5 if core else 1.5),
                marker=dict(size=8, color=_scenario_color(theme, scenario),
                            line=dict(color=theme.surface, width=2)),
                selectedpoints=[list(years).index(y) for y in KEY_YEARS if y in years] if core else None,
                unselected=dict(marker=dict(opacity=0)) if core else None,
                hovertemplate=f"{scenario}: %{{y:+.0f}} cm<extra></extra>",
            ))
            end_labels.append((scenario, float(wide[scenario].iloc[-1])))

    elif extrap is not None and len(extrap):
        color = _scenario_color(theme, "Intermediate")
        _band(fig, extrap["year"], extrap["low_cm"], extrap["high_cm"], color, theme,
              "95% range of trend")
        fig.add_trace(go.Scatter(
            x=extrap["year"], y=extrap["rsl_cm"], name="Trend continued",
            mode="lines", line=dict(color=color, width=2.5, dash="dash"),
            hovertemplate="Trend continued: %{y:+.0f} cm<extra></extra>",
        ))

    if observed is not None and len(observed):
        fig.add_trace(go.Scatter(
            x=observed["year"], y=observed["rsl_cm"], name="Observed (annual)",
            mode="markers", marker=dict(size=5, color=theme.series),
            hovertemplate="Observed %{x}: %{y:+.1f} cm<extra></extra>",
        ))

    # Leave room for the longest end label (~6.5 px per character at 11 px).
    labels = [f"{scenario} {y:+.0f}" for scenario, y in end_labels]
    right = round(6.5 * max(map(len, labels))) + 16 if labels else 12
    fig.update_layout(**_base_layout(theme, 320, hovermode="x unified",
                                     margin=dict(l=64, r=right, t=40, b=48)))
    fig.update_yaxes(title_text=y_title)
    fig.update_xaxes(range=[1990, 2102], dtick=20)
    fig.add_hline(y=0, line=dict(color=theme.axis, width=1))
    for label, (_, y) in zip(labels, end_labels):
        fig.add_annotation(x=2100, y=y, text=label, xanchor="left", xshift=6,
                           showarrow=False, font=dict(size=11, color=theme.ink_secondary))
    return fig


# --- Global mean sea level ---------------------------------------------------

# The GMSL and region charts sit side by side, so they share one height.
GLOBAL_HEIGHT = 420

def gmsl_chart(gmsl: pd.DataFrame, theme: Theme) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=gmsl["date"], y=gmsl["gmsl_mm"], name="Satellite GMSL", mode="lines",
        line=dict(color=theme.series, width=1.5),
        hovertemplate="%{x|%b %Y}: %{y:+.0f} mm<extra></extra>",
    ))
    t = gmsl["year"].to_numpy()
    fit = np.polyval(np.polyfit(t, gmsl["gmsl_mm"], 2), t)
    fig.add_trace(go.Scatter(
        x=gmsl["date"], y=fit, name="Quadratic fit (accelerating)", mode="lines",
        line=dict(color=theme.reference, width=1.5, dash="dash"), hoverinfo="skip",
    ))
    fig.update_layout(**_base_layout(theme, GLOBAL_HEIGHT, hovermode="x unified"))
    fig.update_yaxes(title_text="mm change since 1993")
    return fig


# --- Regions -----------------------------------------------------------------

def region_bars(summary: pd.DataFrame, theme: Theme) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=summary["median_mm_yr"], y=summary["region"], orientation="h",
        marker=dict(color=theme.series, line=dict(color=theme.surface, width=2),
                    cornerradius=4),
        error_x=dict(
            type="data", symmetric=False, color=theme.ink_muted, thickness=1, width=0,
            array=summary["q75_mm_yr"] - summary["median_mm_yr"],
            arrayminus=summary["median_mm_yr"] - summary["q25_mm_yr"],
        ),
        customdata=np.stack([summary["stations"], summary["q25_mm_yr"], summary["q75_mm_yr"],
                             summary["rising_share"] * 100], axis=-1),
        hovertemplate=(
            "<b>%{y}</b><br>Median trend: %{x:+.2f} mm/yr<br>"
            "Middle half of stations: %{customdata[1]:+.1f} to %{customdata[2]:+.1f}<br>"
            "%{customdata[0]} stations · %{customdata[3]:.0f}% significantly rising"
            "<extra></extra>"
        ),
    ))
    fig.update_layout(**_base_layout(theme, GLOBAL_HEIGHT, bargap=0.35,
                                     margin=dict(l=8, r=16, t=8, b=56)))
    fig.update_xaxes(title_text="Median relative sea-level trend (mm/yr)")
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)", automargin=True)
    fig.add_vline(x=0, line=dict(color=theme.axis, width=1))
    return fig
