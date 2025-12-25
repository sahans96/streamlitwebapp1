import streamlit as st
import leafmap.foliumap as leafmap
from streamlit_folium import st_folium
from folium.plugins import Draw
import pystac_client
import planetary_computer
import odc.stac
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from samgeo import SamGeo
from shapely.geometry import shape
import os

# --- HELPER FUNCTION ---
def save_raster(path, data, bbox, crs="EPSG:4326"):
    """Helper to save a numpy array as a GeoTIFF using rasterio directly."""
    # Handle single band (H, W) or multi-band (C, H, W)
    if len(data.shape) == 2:
        count = 1
        height, width = data.shape
    else:
        count, height, width = data.shape
        
    transform = from_bounds(*bbox, width, height)
    
    with rasterio.open(
        path, 'w',
        driver='GTiff',
        height=height,
        width=width,
        count=count,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        if count == 1:
            dst.write(data, 1)
        else:
            for i in range(count):
                dst.write(data[i], i + 1)

# --- APP CONFIG ---
st.set_page_config(layout="wide", page_title="GeoAI Urban Heat")

st.title("🏙️ Urban Heat & Rooftop Analysis")
st.info("1. Draw a rectangle 2. Click Analyze 3. Wait for AI results.")

# Initialize the map in session state
if 'm' not in st.session_state:
    m = leafmap.Map(center=[53.4808, -2.2426], zoom=15)
    m.add_basemap("SATELLITE")
    
    # Add Drawing tools (specifically for the square icon)
    draw = Draw(
        export=True,
        position='topleft',
        draw_options={
            'polyline': False, 
            'rectangle': True, 
            'polygon': True, 
            'circle': False, 
            'marker': False,
            'circlemarker': False
        },
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
    
@st.cache_resource
def load_sam_model(model_type):
    return SamGeo(model_type=model_type)

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
            
            # 2. Search for Landsat 8/9 data
            search = catalog.search(collections=["landsat-c2-l2"], bbox=bbox, limit=1)
            items = search.item_collection()
            
            if len(items) > 0:
                item = items[0]
                # Load Thermal (lwir11) and RGB bands
                data = odc.stac.load([item], bands=["lwir11", "red", "green", "blue"], bbox=bbox).isel(time=0)
                
                # --- HEAT ANALYSIS ---
                thermal_dn = data.lwir11.values
                # Landsat LST Conversion: DN to Celsius
                lst_celsius = (thermal_dn * 0.00341802 + 149.0) - 273.15
                
                heatmap_path = "temp_heatmap.tif"
                # Use the helper function to save
                save_raster(heatmap_path, lst_celsius.astype('float32'), bbox)
                
                # --- ROOFTOP ANALYSIS (SAM) ---
                rgb_path = "temp_rgb.tif"
                red = data.red.values
                green = data.green.values
                blue = data.blue.values
                
                # Stack bands (3, H, W)
                rgb_stack = np.stack([red, green, blue], axis=0) 
                
                # Normalize to 0-255 uint8 for the AI model
                rgb_min, rgb_max = rgb_stack.min(), rgb_stack.max()
                if rgb_max > rgb_min:
                    rgb_stack = ((rgb_stack - rgb_min) / (rgb_max - rgb_min) * 255).astype('uint8')
                else:
                    rgb_stack = rgb_stack.astype('uint8')
                
                save_raster(rgb_path, rgb_stack, bbox)
                
                # Run SAM AI
                #sam = SamGeo(model_type=model_type)
                #mask_path = "rooftop_mask.tif"
                #sam.generate(rgb_path, mask_path, batch=True, foreground=True)
                sam = load_sam_model(model_type)
                mask_path = "rooftop_mask.tif"
                sam.generate(rgb_path, mask_path, batch=True, erosion_kernel=(3, 3), foreground=True)
                
                # Vectorize the rooftops
                vector_path = "rooftops.geojson"
                sam.tiff_to_vector(mask_path, vector_path)
                
                # 3. Display Results
                st.success(f"Analysis complete for {item.datetime.date()}")
                
                # Create a result map
                res_map = leafmap.Map(center=[(bbox[1]+bbox[3])/2, (bbox[0]+bbox[2])/2], zoom=16)
                res_map.add_basemap("SATELLITE")
                res_map.add_raster(heatmap_path, layer_name="Heat Intensity (C)", colormap="hot")
                res_map.add_geojson(vector_path, layer_name="Detected Rooftops")
                
                st.write("### Results Visualization")
                st_folium(res_map, width=700, height=500, key="result_map")
                
                # Download button
                with open(vector_path, "rb") as f:
                    st.download_button("📥 Download Rooftop GeoJSON", f, "rooftops.geojson")
                    
            else:
                st.error("No clear satellite imagery found for this area. Try another spot.")
    else:
        st.warning("Please draw a box on the map first!")
