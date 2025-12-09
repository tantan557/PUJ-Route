# app.py
import io
import os
import pathlib
import pandas as pd
import streamlit as st
import folium
import osmnx as ox
import networkx as nx
from shapely.geometry import MultiPoint
from folium import FeatureGroup, LayerControl
from streamlit_folium import st_folium

# ============================
# CONFIG (you can tweak these)
# ============================
DEFAULT_WALKING_SPEED_MPS = 1.33  # ~5 km/h
DEFAULT_TIME_RANGES = [5, 10]     # minutes
DEFAULT_DIST = 4000               # meters (OSMnx graph extent)
ICON_SIZE = (40, 40)
ICON_ANCHOR = (20, 40)

# Default route icons (used if you don't provide custom ones)
DEFAULT_ROUTE_ICONS = [
    "https://cdn-icons-png.flaticon.com/512/3448/3448316.png",
    "https://cdn-icons-png.flaticon.com/512/3448/3448339.png",
    "https://cdn-icons-png.flaticon.com/512/3448/3448316.png"
]

# ============================
# Streamlit UI
# ============================
st.set_page_config(page_title="Isochrone Map Generator", layout="wide")
st.title("Isochrone Map Generator — Upload CSV / Excel")
st.write("Upload one or more CSV/Excel files (each file = one route). Map will be generated below.")

# Center the uploader visually by using columns (optional cosmetic)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    uploaded_files = st.file_uploader(
        "Upload CSV or Excel files (multiple allowed)",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True
    )

st.markdown("---")

# Sidebar settings
with st.sidebar.expander("Map settings (advanced)", expanded=False):
    walking_speed_mps = st.number_input(
        "Walking speed (m/s)", value=DEFAULT_WALKING_SPEED_MPS, step=0.01, format="%.2f"
    )
    time_ranges = st.multiselect(
        "Time ranges (minutes) to generate",
        options=[1,2,3,4,5,6,7,8,9,10,15,20,30],
        default=DEFAULT_TIME_RANGES
    )
    if not time_ranges:
        time_ranges = DEFAULT_TIME_RANGES
    dist_m = st.number_input("OSMnx graph dist (meters)", value=DEFAULT_DIST, step=500)
    simplify_polygons = st.checkbox("Simplify polygons (reduce size)", value=False)
    simplify_tolerance = st.number_input("Simplify tolerance (degrees)", value=0.0008, step=0.0001, format="%.4f")

# Helper: read uploaded file into DataFrame
@st.cache_data(show_spinner=False)
def read_file_to_df(uploaded_file):
    name = uploaded_file.name.lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            # Excel (take first sheet)
            df = pd.read_excel(uploaded_file, sheet_name=0)
    except Exception as e:
        st.error(f"Failed to read {uploaded_file.name}: {e}")
        return None
    return df

# If no files uploaded, show example instructions
if not uploaded_files:
    st.info("Upload CSV or Excel files to generate the map. Each uploaded file will be treated as a route.")
    st.caption("Expected columns in each file: lat, lon, name (stop name). Optional: stop_number, address.")
    st.stop()

# Read files
routes = {}  # route_name -> dataframe
for idx, f in enumerate(uploaded_files):
    df = read_file_to_df(f)
    if df is None:
        st.warning(f"Could not read {f.name}. Skipping.")
        continue

    # Basic column normalization: lower-case columns
    df.columns = [c.strip() for c in df.columns]
    df_lower = df.rename(columns={c: c.strip().lower() for c in df.columns})
    # ensure required columns exist
    if not {"lat", "lon"}.issubset(set(df_lower.columns)):
        st.error(f"File {f.name} must contain 'lat' and 'lon' columns (case-insensitive). Skipping.")
        continue
    # route name = filename without extension
    route_name = pathlib.Path(f.name).stem
    routes[route_name] = df_lower.copy()

if not routes:
    st.error("No valid routes uploaded.")
    st.stop()

# Assign icons per route (rotate through default icons)
route_icons = {}
icon_list = DEFAULT_ROUTE_ICONS
for i, route_name in enumerate(routes.keys()):
    route_icons[route_name] = icon_list[i % len(icon_list)]

# ============================
# Build Folium Map
# ============================
# Map center from first route's first stop
first_route_df = next(iter(routes.values()))
center_lat = float(first_route_df['lat'].iloc[0])
center_lon = float(first_route_df['lon'].iloc[0])
m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

colors = {t: ("#fff700" if t == min(time_ranges) else "#1f77b4") for t in time_ranges}
# if more than two time ranges, color mapping will reuse these two for simplicity
if len(time_ranges) > 2:
    # map additional times to the second color
    for t in time_ranges:
        if t != min(time_ranges):
            colors[t] = "#1f77b4"

# Main generation: iterate routes and stops
spinner_text = st.empty()
spinner_text.info("Generating map — this may take a while for many stops. Please wait...")

for route_idx, (route_name, df) in enumerate(routes.items(), start=1):
    # route title (highlighted)
    highlighted_route_title = f"🔥 {route_name}"

    # FeatureGroup for route title (acts as top-level toggle)
    route_group = FeatureGroup(name=highlighted_route_title, show=False)
    route_group.add_to(m)

    # iterate stops
    for i, row in df.iterrows():
        # attempt to access columns (lower-case)
        stop_name = row.get('name', f"Stop {i+1}")
        stop_number = row.get('stop_number', i+1)
        lat = float(row['lat'])
        lon = float(row['lon'])

        # Stop-level group for isochrones
        stop_group_name = f"Stop {stop_number} → {stop_name}"
        stop_group = FeatureGroup(name=stop_group_name, show=False)

        # Marker icon
        icon_url = route_icons.get(route_name)
        icon = folium.CustomIcon(icon_image=icon_url, icon_size=ICON_SIZE, icon_anchor=ICON_ANCHOR)

        # Popup: Stop # (bold) on first line, Stop name on second line
        popup_html = f"""<div><b>Stop {stop_number}</b><br>{stop_name}</div>"""
        folium.Marker(location=[lat, lon], icon=icon, popup=popup_html).add_to(route_group)

        # Build OSMnx graph, compute time on edges
        try:
            G = ox.graph_from_point((lat, lon), dist=dist_m, network_type='walk')
        except Exception as e:
            st.warning(f"OSMnx graph failed for {stop_name} ({route_name}): {e}")
            continue

        for u, v, k, data in G.edges(keys=True, data=True):
            if "length" in data:
                data["time"] = data["length"] / walking_speed_mps

        # nearest node
        try:
            center_node = ox.distance.nearest_nodes(G, lon, lat)
        except Exception as e:
            st.warning(f"Nearest node failed for {stop_name} ({route_name}): {e}")
            continue

        # Build isochrone polygons for each time range
        for t in time_ranges:
            sec = t * 60
            subG = nx.ego_graph(G, center_node, radius=sec, distance="time")
            pts = [(G.nodes[n]["x"], G.nodes[n]["y"]) for n in subG.nodes()]
            if len(pts) < 3:
                continue
            poly = MultiPoint(pts).convex_hull.buffer(0.002)
            if simplify_polygons:
                # simplify (reduces size)
                poly = poly.simplify(simplify_tolerance, preserve_topology=True)

            folium.GeoJson(
                data=poly,
                style_function=lambda x, m=t: {
                    "fillOpacity": 0.4,
                    "weight": 2,
                    "color": colors[m],
                    "fillColor": colors[m]
                },
                name=f"Stop {stop_number} → {stop_name} {t} min"
            ).add_to(stop_group)

        # add stop group to map (so it appears in LayerControl)
        stop_group.add_to(m)

spinner_text.empty()

# Add LayerControl and legend (as in your original script)
LayerControl(collapsed=False).add_to(m)

legend_html = """
<div style="position:fixed; bottom:30px; left:30px; 
background:white; z-index:9999; padding:10px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.4)">
<b>Isochrone Walk Time</b><br>
<span style='background:#fff700;padding:5px 15px; display:inline-block;'></span> {min_t} min<br>
<span style='background:#1f77b4;padding:5px 15px; display:inline-block;'></span> {max_t} min<br>
</div>
""".format(min_t=min(time_ranges), max_t=max(time_ranges))
m.get_root().html.add_child(folium.Element(legend_html))

# ============================
# Show map in Streamlit
# ============================
st.success("Map generation completed.")
st.write("Map (interactive) — use the layer control to toggle routes/stops/isochrones.")
st_data = st_folium(m, width=1200, height=700)

# ============================
# Offer download of HTML
# ============================
html_bytes = m.get_root().render().encode("utf-8")
st.download_button(
    label="Download map as HTML",
    data=html_bytes,
    file_name="isochrone_map.html",
    mime="text/html"
)
