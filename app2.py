import streamlit as st
import geopandas as gpd
from shapely.geometry import Point
from streamlit_js_eval import get_geolocation  # pip install streamlit-js-eval
import pandas as pd
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
import requests
from dotenv import load_dotenv
import os

# ========== CONFIG ==============
load_dotenv()  # Load .env file
ORS_API_KEY = os.getenv("ORS_API_KEY")
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car"

# Load polling unit data
@st.cache_data
def load_data():
    return gpd.read_file("geojson/polling_units.geojson")

# Find closest polling units (by geodesic distance)
def find_closest_polling_units(lat, lon, polling_units, n=5):
    user_coords = (lat, lon)
    polling_units = polling_units.copy()

    distances = []
    for _, pu in polling_units.iterrows():
        pu_coords = (pu.geometry.y, pu.geometry.x)
        dist_m = geodesic(user_coords, pu_coords).meters
        distances.append(dist_m)

    polling_units["Distance (m)"] = distances
    nearest_pus = polling_units.nsmallest(n, "Distance (m)")

    df = pd.DataFrame({
        "Polling Unit": nearest_pus["name"],
        "Ward": nearest_pus["ward"],
        "LGA": nearest_pus["lga"],
        "State": nearest_pus["state"],
        "Latitude": nearest_pus.geometry.y,
        "Longitude": nearest_pus.geometry.x,
        "Distance (m)": nearest_pus["Distance (m)"].round(2)
    })
    return df

# Call OpenRouteService to get route
def get_route_geojson(start_lon, start_lat, end_lon, end_lat):
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }
    body = {
        "coordinates": [
            [start_lon, start_lat],
            [end_lon, end_lat]
        ],
        "format": "geojson"
    }
    try:
        resp = requests.post(ORS_DIRECTIONS_URL, json=body, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"Routing API error: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        st.error(f"Routing API request failed: {e}")
        return None

# ========== STREAMLIT APP ==============
st.set_page_config(page_title="Polling Unit Finder", layout="wide")
st.title(" Veegil Polling Unit Location Finder with Road Route")

polling_units = load_data()

# Detect GPS automatically
loc = get_geolocation()
lat, lon = None, None

if loc is not None and "coords" in loc:
    lat = loc["coords"]["latitude"]
    lon = loc["coords"]["longitude"]
    st.success(f" Location detected: {lat:.5f}, {lon:.5f}")

# Fallback to manual input
if not lat or not lon:
    st.warning("GPS access denied. Please enter coordinates manually.")
    lat = st.number_input("Enter Latitude", value=9.082, format="%.6f")
    lon = st.number_input("Enter Longitude", value=8.6753, format="%.6f")

n_units = st.slider("How many nearest polling units to consider", min_value=1, max_value=10, value=5)

if lat and lon:
    df_results = find_closest_polling_units(lat, lon, polling_units, n=n_units)
    st.subheader(f"{n_units} Nearest Polling Units")
    st.dataframe(df_results)

    # Download CSV
    csv_bytes = df_results.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download as CSV",
        data=csv_bytes,
        file_name="nearest_polling_units.csv",
        mime="text/csv"
    )

    # Let user select one polling unit to draw route
    pu_options = df_results["Polling Unit"].tolist()
    selected_pu = st.selectbox("Select a polling unit to show route:", pu_options)

    selected_row = df_results[df_results["Polling Unit"] == selected_pu].iloc[0]

    # Map
    m = folium.Map(location=[lat, lon], zoom_start=12)
    folium.Marker([lat, lon], popup="You are here", icon=folium.Icon(color="blue")).add_to(m)

    # Markers for polling units
    for _, row in df_results.iterrows():
        folium.Marker(
            [row["Latitude"], row["Longitude"]],
            popup=f"<b>{row['Polling Unit']}</b><br>{row['Ward']} | {row['LGA']} | {row['State']}<br>Distance {row['Distance (m)']:.1f} m",
            icon=folium.Icon(color="red" if row["Polling Unit"] == selected_pu else "green")
        ).add_to(m)

    # Road route to selected polling unit
    route_geojson = get_route_geojson(
        lon, lat,
        selected_row["Longitude"], selected_row["Latitude"]
    )
    if route_geojson:
        folium.GeoJson(route_geojson, name="route", tooltip="Driving route").add_to(m)

    st_folium(m, width=800, height=500)
