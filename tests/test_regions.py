import pytest

from slr.regions import coastal_region, ocean_basin


@pytest.mark.parametrize("name, lat, lon, basin", [
    ("Miami (Virginia Key)", 25.73, -80.16, "Atlantic"),
    ("San Francisco", 37.81, -122.47, "Pacific"),
    ("Honolulu", 21.31, -157.87, "Pacific"),
    ("Galveston", 29.31, -94.79, "Atlantic"),
    ("Coatzacoalcos (Gulf of Mexico)", 18.1, -94.4, "Atlantic"),
    ("Acapulco", 16.8, -99.9, "Pacific"),
    ("Balboa (Panama, Pacific side)", 8.96, -79.57, "Pacific"),
    ("Cristobal (Panama, Caribbean side)", 9.35, -79.92, "Atlantic"),
    ("Valparaiso", -33.03, -71.63, "Pacific"),
    ("Buenos Aires", -34.6, -58.4, "Atlantic"),
    ("Cape Town", -33.9, 18.4, "Atlantic"),
    ("Durban", -29.9, 31.0, "Indian"),
    ("Mumbai", 18.9, 72.8, "Indian"),
    ("Ko Lak (Gulf of Thailand)", 11.8, 99.8, "Pacific"),
    ("Penang (Malacca Strait)", 5.4, 100.3, "Indian"),
    ("Singapore", 1.2, 103.8, "Pacific"),
    ("Fremantle", -32.1, 115.7, "Indian"),
    ("Cairns (Coral Sea)", -16.9, 145.8, "Pacific"),
    ("Sydney", -33.9, 151.2, "Pacific"),
    ("Tokyo Bay", 35.1, 139.6, "Pacific"),
    ("Marseille", 43.3, 5.3, "Mediterranean & Black Sea"),
    ("Santander (Bay of Biscay)", 43.5, -3.8, "Atlantic"),
    ("Sevastopol", 44.6, 33.5, "Mediterranean & Black Sea"),
    ("Stockholm", 59.3, 18.1, "Baltic Sea"),
    ("Oslo", 59.9, 10.8, "Atlantic"),
    ("Cuxhaven (North Sea)", 53.9, 8.7, "Atlantic"),
    ("Prudhoe Bay", 70.4, -148.5, "Arctic"),
    ("Argentine Islands", -65.2, -64.3, "Southern"),
])
def test_ocean_basin(name, lat, lon, basin):
    assert ocean_basin(lat, lon) == basin, name


@pytest.mark.parametrize("sid, lat, lon, region", [
    ("8723214", 25.73, -80.16, "US East Coast"),
    ("8724580", 24.55, -81.81, "US Gulf Coast"),  # Key West faces the Gulf
    ("8771450", 29.31, -94.79, "US Gulf Coast"),
    ("9414290", 37.81, -122.47, "US West Coast"),
    ("9461380", 51.86, -176.63, "Alaska"),
    ("1612340", 21.31, -157.87, "Hawaii & Pacific Islands"),
    ("9755371", 18.46, -66.12, "Caribbean & Bermuda"),
    ("2695540", 32.37, -64.70, "Caribbean & Bermuda"),
])
def test_us_coastal_region(sid, lat, lon, region):
    assert coastal_region(sid, "US", "USA", lat, lon) == region


@pytest.mark.parametrize("country, lat, lon, region", [
    ("Spain", 43.5, -3.8, "Western Europe"),
    ("Spain", 36.7, -4.4, "Mediterranean & Black Sea"),
    ("Finland", 60.1, 25.0, "Northern Europe & Baltic"),
    ("Russia", 43.1, 131.9, "East Asia"),
    ("Russia", 59.9, 30.3, "Northern Europe & Baltic"),
    ("Japan", 35.1, 139.6, "East Asia"),
    ("Nauru-B", -0.5, 166.9, "Hawaii & Pacific Islands"),
    ("Atlantis", 0.0, 0.0, "Other"),
])
def test_global_coastal_region(country, lat, lon, region):
    assert coastal_region("000-000", "Global", country, lat, lon) == region
