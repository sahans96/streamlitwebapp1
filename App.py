import streamlit as st
import leafmap.foliumap as leafmap
from streamlit_folium import st_folium
from folium.plugins import Draw
import pystac_client
import planetary_computer
import odc.stac
from samgeo import SamGeo
from shapely.geometry import shape
import os

st.set_page_config(layout="wide", page_title="GeoAI Urban Heat")

st.title("🏙️ Urban Heat & Rooftop Analysis")
st.info("Draw a rectangle on the map to start.")

# Initialize the map in session state
if 'm' not in st.session_state:
    m = leafmap.Map(center=[53.4808, -2.2426], zoom=13)
    m.add_basemap("SATELLITE")

# 2. EXPLICITLY add the Draw control (This fixes the missing icon)
    # This adds the toolbar with the square, polygon, and line tools
    draw = Draw(
        export=True,
        filename='data.geojson',
        position='topleft',
        draw_options={
            'polyline': False,
            'rectangle': True, # This is your "square" icon
            'polygon': True,
            'circle': False,
            'marker': False,
            'circlemarker': False,
        },
        edit_options={'edit': True}
    )
    draw.add_to(m)
    st.session_state.m = m

col1, col2 = st.columns([3, 1])

with col1:
    # IMPORTANT: Use st_folium to capture the drawing data
    # This replaces m.to_streamlit() which was causing your error
    output = st_folium(st.session_state.m, width=None, height=600, key="geo_map")

with col2:
    st.subheader("Controls")
    # Use vit_b (Base) because vit_h (Huge) will crash the free 1GB RAM cloud server
    model_type = st.selectbox("AI Model Size", ["vit_b", "vit_l"], index=0)
    process_btn = st.button("🚀 Analyze Area")

if process_btn:
    # Fix: Check if output is a dict and has 'last_active_drawing'
    if output and "last_active_drawing" in output and output["last_active_drawing"]:
        roi_geojson = output["last_active_drawing"]
        bbox = shape(roi_geojson['geometry']).bounds
        
        with st.spinner("Fetching Satellite Data..."):
            catalog = pystac_client.Client.open(
                "https://planetarycomputer.microsoft.com/api/stac/v1",
                modifier=planetary_computer.sign_inplace
            )
            # Fetch Landsat 8/9 data for Thermal/Heat mapping
            search = catalog.search(collections=["landsat-c2-l2"], bbox=bbox, limit=1)
            items = search.item_collection()
            
            if len(items) > 0:
                st.success(f"Found imagery from {items[0].datetime.date()}")
                # Add logic for LST and SAM here...
            else:
                st.error("No imagery found for this spot.")
    else:
        st.warning("Please use the square icon on the map to draw an area first!")
