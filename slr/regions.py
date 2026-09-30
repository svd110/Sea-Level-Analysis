"""Assign tide-gauge stations to ocean basins and coastal regions.

Both groupings are rule-based approximations from coordinates (and, for
coastal regions, the country in the station name). They are good enough to
aggregate ~500 gauges for a regional comparison, not a substitute for proper
basin polygons. Boundary cases are pinned down in ``tests/test_regions.py``.
"""

from __future__ import annotations

BASINS = [
    "Pacific", "Atlantic", "Indian", "Mediterranean & Black Sea",
    "Baltic Sea", "Arctic", "Southern",
]


def _is_mediterranean(lat: float, lon: float) -> bool:
    med = 30 <= lat <= 46 and -5.6 <= lon <= 36.5 and not (lon < 3 and lat > 42.5)
    black_sea = 40.5 <= lat <= 47 and 27.5 <= lon <= 42
    return med or black_sea


def _is_baltic(lat: float, lon: float) -> bool:
    if not (53.5 <= lat < 66 and 9.7 <= lon <= 31):
        return False
    # Oslofjord / Skagerrak belong to the North Sea side.
    return not (lat > 58.5 and lon < 11.5)


def _americas_pacific(lat: float, lon: float) -> bool:
    """West of the Americas' continental divide, approximated by latitude band."""
    if lat >= 30:
        return lon < -100
    if lat >= 18.5:
        return lon < -103
    if lat >= 17:
        return lon < -100  # Coatzacoalcos (Gulf) vs Acapulco (Pacific)
    if lat >= 15:
        return lon < -92
    if lat >= 7:
        return lon < -84.5 or (lat < 9.2 and lon < -77.5)
    if lat >= 0:
        return lon < -77
    return lon < -70


def _eastern_indian(lat: float, lon: float) -> bool:
    """Indian Ocean east of 100°E: Andaman Sea, Malacca Strait, W/S Australia."""
    if lon < 102 and 1 < lat < 7.5:
        return True  # Strait of Malacca
    if lon < 99 and lat >= 7.5:
        return True  # Andaman Sea
    # Indian-Ocean-facing Australia: the west and north, and the south coast
    # as far east as Bass Strait. Queensland faces the Coral Sea (Pacific).
    return lat < -10 and (lon < 142 or (lat < -30 and lon < 146))


def ocean_basin(lat: float, lon: float) -> str:
    if lat >= 66:
        return "Arctic"
    if lat <= -60:
        return "Southern"
    if _is_mediterranean(lat, lon):
        return "Mediterranean & Black Sea"
    if _is_baltic(lat, lon):
        return "Baltic Sea"
    if lon < -20:
        return "Pacific" if _americas_pacific(lat, lon) else "Atlantic"
    if lon < 20:
        return "Atlantic"
    if lon < 100:
        # The Gulf of Thailand opens onto the South China Sea.
        gulf_of_thailand = 6 <= lat <= 14 and lon >= 99.2
        return "Pacific" if gulf_of_thailand else "Indian"
    return "Indian" if _eastern_indian(lat, lon) else "Pacific"


# --- Coastal regions ---------------------------------------------------------

_COUNTRY_REGION = {
    "canada": "Canada",
    "mexico": "Mexico & Central America",
    "panama": "Mexico & Central America",
    "el salvador": "Mexico & Central America",
    "cuba": "Caribbean & Bermuda",
    "bahamas": "Caribbean & Bermuda",
    "martinique": "Caribbean & Bermuda",
    "colombia": "South America",
    "ecuador": "South America",
    "peru": "South America",
    "chile": "South America",
    "argentina": "South America",
    "uruguay": "South America",
    "brazil": "South America",
    "falkland islands": "South America",
    "south africa": "Africa & Middle East",
    "namibia": "Africa & Middle East",
    "ghana": "Africa & Middle East",
    "mozambique": "Africa & Middle East",
    "tanzania": "Africa & Middle East",
    "kenya": "Africa & Middle East",
    "egypt": "Africa & Middle East",
    "yemen": "Africa & Middle East",
    "mauritius": "Africa & Middle East",
    "reunion": "Africa & Middle East",
    "india": "South Asia",
    "pakistan": "South Asia",
    "maldives": "South Asia",
    "japan": "East Asia",
    "china": "East Asia",
    "hong kong": "East Asia",
    "taiwan": "East Asia",
    "korea": "East Asia",
    "south korea": "East Asia",
    "north korea": "East Asia",
    "malaysia": "Southeast Asia",
    "thailand": "Southeast Asia",
    "vietnam": "Southeast Asia",
    "philippines": "Southeast Asia",
    "singapore": "Southeast Asia",
    "indonesia": "Southeast Asia",
    "australia": "Australia & New Zealand",
    "new zealand": "Australia & New Zealand",
    "antarctica": "Antarctica",
    "usa": "Hawaii & Pacific Islands",  # Johnston Island, French Frigate Shoals
}

_PACIFIC_ISLANDS = {
    "kiribati", "french polynesia", "federated states of micronesia",
    "northern mariana islands", "palau", "nauru-b", "nauru", "marshall islands",
    "tuvalu", "solomon islands", "fiji", "cook islands",
}

_EUROPE = {
    "uk", "ireland", "iceland", "norway", "sweden", "finland", "denmark",
    "netherlands", "belgium", "germany", "poland", "lithuania", "france",
    "spain", "portugal", "gibraltar", "italy", "greece", "croatia", "bulgaria",
    "romania", "ukraine", "georgia",
}
_NORDIC = {"iceland", "norway", "sweden", "finland", "denmark"}


def _us_region(station_id: str, lat: float, lon: float) -> str:
    if station_id.startswith("1") or (lon < -150 and lat < 30):
        return "Hawaii & Pacific Islands"
    if station_id.startswith("2") or (lat < 19.5 and lon > -68.5):
        return "Caribbean & Bermuda"  # Bermuda, Puerto Rico, US Virgin Islands
    if lat > 51:  # includes the Aleutians
        return "Alaska"
    if lon < -115:
        return "US West Coast"
    if lat < 31 and -98 < lon < -81.2:
        return "US Gulf Coast"
    return "US East Coast"


def _europe_region(country: str, lat: float, lon: float) -> str:
    basin = ocean_basin(lat, lon)
    if basin == "Mediterranean & Black Sea":
        return "Mediterranean & Black Sea"
    if basin in ("Baltic Sea", "Arctic") or country in _NORDIC:
        return "Northern Europe & Baltic"
    return "Western Europe"


def coastal_region(station_id: str, affil: str, country: str, lat: float, lon: float) -> str:
    if affil == "US":
        return _us_region(station_id, lat, lon)
    key = country.strip().lower()
    if key in _PACIFIC_ISLANDS:
        return "Hawaii & Pacific Islands"
    if key in _EUROPE:
        return _europe_region(key, lat, lon)
    if key == "russia":
        if lon > 100:
            return "East Asia"
        if ocean_basin(lat, lon) == "Mediterranean & Black Sea":
            return "Mediterranean & Black Sea"
        return "Northern Europe & Baltic"
    return _COUNTRY_REGION.get(key, "Other")
