# #python -m venv spatial
# .\spatial\Scripts\Activate.ps1
# spatial\Scripts\activate CMD
# pip install geopandas pandas shapely streamlit streamlit-js-eval python-dotenv
# streamlit run app.py

import streamlit as st
import geopandas as gpd
from shapely.geometry import Point
from streamlit_js_eval import get_geolocation
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
import pandas as pd
import requests
from dotenv import load_dotenv
import os

# Load ORS API key
load_dotenv()
ORS_API_KEY = os.getenv("ORS_API_KEY")
ORS_DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

st.set_page_config(page_title="Nigeria Polling Location Finder", layout="wide")
st.title(" Veegil Polling Unit Location Finder")
st.markdown("Find your **nearest Polling Units** with **real routes** in Nigeria.")

@st.cache_data
def load_polling_units():
    return gpd.read_file("geojson/polling_units.geojson")

polling_units = load_polling_units()

def get_road_route_and_distance(start_lat, start_lon, end_lat, end_lon):
    """Call ORS API for a road route and distance/time."""
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "format": "geojson"
    }
    r = requests.post(ORS_DIRECTIONS_URL, json=body, headers=headers)
    if r.status_code == 200:
        data = r.json()
        distance = data["features"][0]["properties"]["segments"][0]["distance"]  # m
        duration = data["features"][0]["properties"]["segments"][0]["duration"]  # s
        return data, distance, duration
    else:
        return None, float('inf'), float('inf')

def find_nearest_polling_units(lat, lon, n=5):
    """Return n nearest polling units sorted by real road distance."""
    # Step 1: Quick filter by geodesic distance
    distances = polling_units.apply(
        lambda row: geodesic((lat, lon), (row.geometry.y, row.geometry.x)).meters, axis=1
    )
    pu = polling_units.copy()
    pu["geo_distance_m"] = distances
    pu = pu.nsmallest(n * 3, "geo_distance_m")  # take a bit larger set to refine

    # Step 2: Real road distance from ORS
    routes = []
    for idx, row in pu.iterrows():
        route_geojson, dist_m, dur_s = get_road_route_and_distance(
            lat, lon, row.geometry.y, row.geometry.x
        )
        routes.append((idx, dist_m, dur_s, route_geojson))

    # Attach back to DataFrame
    pu["road_distance_m"] = [r[1] for r in routes]
    pu["duration_s"] = [r[2] for r in routes]
    pu["route_geojson"] = [r[3] for r in routes]

    # Sort by real road distance
    pu = pu.sort_values("road_distance_m").head(n)

    return pu

# ========================= UI ===========================

# Auto GPS detection
loc = get_geolocation()
lat, lon = None, None

if loc is not None and "coords" in loc:
    lat = loc["coords"]["latitude"]
    lon = loc["coords"]["longitude"]
    st.success(f"📍 Detected Location: {lat:.5f}, {lon:.5f}")

if not lat or not lon:
    st.warning("GPS access denied. Please enter coordinates manually.")
    lat = st.number_input("Enter Latitude", value=9.082, format="%.6f")
    lon = st.number_input("Enter Longitude", value=8.6753, format="%.6f")

n_nearest = st.slider("Number of nearest polling units", 1, 10, 5)

if st.button("Find Nearest Polling Units"):
    with st.spinner("Fetching nearest polling units..."):
        nearest_pus = find_nearest_polling_units(lat, lon, n=n_nearest)

    st.subheader("Nearest Polling Units (sorted by shortest distance)")
    df_display = nearest_pus[["name", "ward", "lga", "state", "road_distance_m", "duration_s"]].copy()
    df_display.rename(columns={
        "name": "Polling Unit",
        "ward": "Ward",
        "lga": "LGA",
        "state": "State",
        "road_distance_m": "Road Distance (m)",
        "duration_s": "Duration (s)"
    }, inplace=True)
    st.dataframe(df_display)

    # Download button
    csv = df_display.to_csv(index=False).encode("utf-8")
    st.download_button("Download Nearest Polling Units (CSV)", csv, "nearest_polling_units.csv", "text/csv")

    # Let user pick one to show route
    selected_pu = st.selectbox(
        "Select a Polling Unit to show route",
        options=df_display["Polling Unit"].tolist()
    )

    # Show map
    if selected_pu:
        selected_row = nearest_pus[nearest_pus["name"] == selected_pu].iloc[0]
        m = folium.Map(location=[lat, lon], zoom_start=12)
        folium.Marker([lat, lon], popup="Your Location", icon=folium.Icon(color="blue")).add_to(m)
        folium.Marker(
            [selected_row.geometry.y, selected_row.geometry.x],
            popup=f"{selected_row['name']} ({selected_row['ward']} Ward)",
            icon=folium.Icon(color="red")
        ).add_to(m)

        # Draw route
        route_geojson = selected_row["route_geojson"]
        if route_geojson:
            folium.GeoJson(
                route_geojson,
                name="Route",
                style_function=lambda x: {"color": "green", "weight": 4}
            ).add_to(m)

        st_folium(m, width=800, height=500)
