import streamlit as st
import leafmap.foliumap as leafmap
from streamlit_folium import st_folium
from folium.plugins import Draw
import pystac_client
import planetary_computer
import odc.stac
import numpy as np
import rasterio
from samgeo import SamGeo
from shapely.geometry import shape
import os

st.set_page_config(layout="wide", page_title="GeoAI Urban Heat")

st.title("🏙️ Urban Heat & Rooftop Analysis")
st.info("1. Draw a rectangle 2. Click Analyze 3. Wait for AI results.")

# Initialize the map in session state
if 'm' not in st.session_state:
    m = leafmap.Map(center=[53.4808, -2.2426], zoom=15)
    m.add_basemap("SATELLITE")
    
    # Add Drawing tools
    draw = Draw(
        export=True,
        position='topleft',
        draw_options={'polyline': False, 'rectangle': True, 'polygon': True, 'circle': False, 'marker': False},
        edit_options={'edit': True}
    )
    draw.add_to(m)
    st.session_state.m = m

col1, col2 = st.columns([3, 1])

with col1:
    # Captures the drawing data from the user
    output = st_folium(st.session_state.m, width=None, height=600, key="geo_map")

with col2:
    st.subheader("Controls")
    model_type = st.selectbox("AI Model Size", ["vit_b", "vit_l"], index=0, help="vit_b is recommended for the free cloud tier.")
    process_btn = st.button("🚀 Analyze Area")

if process_btn:
    if output and "last_active_drawing" in output and output["last_active_drawing"]:
        roi_geojson = output["last_active_drawing"]
        bbox = shape(roi_geojson['geometry']).bounds
        
        with st.spinner("Processing... This may take 1-2 minutes."):
            # 1. Access Microsoft Planetary Computer
            catalog = pystac_client.Client.open(
                "https://planetarycomputer.microsoft.com/api/stac/v1",
                modifier=planetary_computer.sign_inplace
            )
            
            # 2. Search for Landsat 8/9 data (includes Thermal and RGB)
            search = catalog.search(collections=["landsat-c2-l2"], bbox=bbox, limit=1)
            items = search.item_collection()
            
            if len(items) > 0:
                item = items[0]
                # Load Thermal (B10) and RGB (B4, B3, B2)
                data = odc.stac.load([item], bands=["lwir11", "red", "green", "blue"], bbox=bbox).isel(time=0)
                
                # --- HEAT ANALYSIS ---
                # Landsat 8/9 LST Formula: (DN * 0.00341802) + 149.0 (Kelvin)
                thermal_dn = data.lwir11.values
                lst_kelvin = (thermal_dn * 0.00341802) + 149.0
                lst_celsius = lst_kelvin - 273.15
                
                # Save Heatmap as temporary TIFF
                heatmap_path = "temp_heatmap.tif"
                leafmap.numpy_to_cog(lst_celsius, heatmap_path, bounds=bbox)
                
                # --- ROOFTOP ANALYSIS (SAM) ---
                # Create an RGB image for the AI
                rgb_path = "temp_rgb.tif"
                # Stack RGB bands and normalize for SAM
                rgb_stack = np.stack([data.red, data.green, data.blue], axis=-1)
                leafmap.numpy_to_cog(rgb_stack, rgb_path, bounds=bbox)
                
                sam = SamGeo(model_type=model_type)
                mask_path = "rooftop_mask.tif"
                # This runs the segmentation
                sam.generate(rgb_path, mask_path, batch=True, foreground=True)
                
                # Vectorize the rooftops
                vector_path = "rooftops.geojson"
                sam.tiff_to_vector(mask_path, vector_path)
                
                # 3. Display Results
                st.success(f"Analysis complete for {item.datetime.date()}")
                
                # Update the map with results
                res_map = leafmap.Map(center=[(bbox[1]+bbox[3])/2, (bbox[0]+bbox[2])/2], zoom=16)
                res_map.add_basemap("SATELLITE")
                res_map.add_raster(heatmap_path, layer_name="Heat Intensity (C)", colormap="hot")
                res_map.add_geojson(vector_path, layer_name="Detected Rooftops")
                
                st.write("### Results Visualization")
                st_folium(res_map, width=700, height=500)
                
                # Download button for the rooftop data
                with open(vector_path, "rb") as f:
                    st.download_button("📥 Download Rooftop GeoJSON", f, "rooftops.geojson")
                    
            else:
                st.error("No clear satellite imagery found for this area. Try another spot.")
    else:
        st.warning("Please draw a box on the map first!")
