"""
app.py — Main Streamlit Interactive Dashboard for ENVIRON-X Digital Twin (Solar Harvesting & Critical CH Handoff Engine).
"""

from __future__ import annotations
import math
import time
import pandas as pd
import numpy as np
import pydeck as pdk
import plotly.graph_objects as go
import streamlit as st

from simulation import (
    WorldSimulation,
    init_world,
    update_sensors_step,
    add_log,
)
from network import (
    leach_elect_clusters,
    consume_energy_step,
    compute_network_stats,
    get_inter_node_links,
)
from ai import (
    run_multi_node_consensus,
    evaluate_edge_ai,
)

# -----------------------------------------------------------------------------
# PAGE CONFIGURATION
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="ENVIRON-X — Environmental Intelligence Network",
    layout="wide",
    initial_sidebar_state="collapsed",
)

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=3000, key="hw_telemetry_refresher")
except Exception:
    pass

# -----------------------------------------------------------------------------
# CUSTOM LIGHT ENGINEERING THEME CSS
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@800;900&family=Plus+Jakarta+Sans:wght@700;800;900&display=swap');

        .stApp {
            background-color: #f8fafc !important;
            color: #0f172a !important;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            font-size: 15px !important;
        }
        
        header[data-testid="stHeader"] { display: none !important; }
        footer { display: none !important; }
        
        .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 0.5rem !important;
            padding-left: 1.0rem !important;
            padding-right: 1.0rem !important;
            max-width: 100% !important;
        }

        div[data-baseweb="select"] > div {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border-color: #cbd5e1 !important;
            font-size: 14px !important;
        }

        button[kind="secondary"], button[kind="primary"], .stButton > button {
            background-color: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid #cbd5e1 !important;
            border-radius: 6px !important;
            font-weight: 700 !important;
            font-size: 13.5px !important;
        }

        button[kind="secondary"]:hover, button[kind="primary"]:hover, .stButton > button:hover {
            background-color: #f1f5f9 !important;
            border-color: #94a3b8 !important;
            color: #0284c7 !important;
        }

        .hdr-box {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }
        .hdr-badge {
            background: #d1fae5;
            border: 1px solid #10b981;
            color: #047857;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 800;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .card-box {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 14px;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        }
        .card-hdr {
            font-size: 15.5px;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 6px;
        }

        .sensor-row {
            display: flex;
            justify-content: space-between;
            padding: 7px 0;
            border-bottom: 1px solid #f1f5f9;
            font-size: 13.5px;
        }
        .sensor-label { color: #475569; font-weight: 500; }
        .sensor-val { font-weight: 800; color: #0f172a; font-family: monospace; font-size: 14px; }
        .trend-up { color: #dc2626; font-weight: bold; font-size: 11px; }
        .trend-dn { color: #0284c7; font-weight: bold; font-size: 11px; }
        .trend-ok { color: #059669; font-weight: 700; font-size: 11px; }

        .zone-badge-forest { background: #d1fae5; border: 1px solid #10b981; color: #047857; padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: 800; }
        .zone-badge-river { background: #e0f2fe; border: 1px solid #0284c7; color: #0369a1; padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: 800; }
        .zone-badge-slope { background: #f3e8ff; border: 1px solid #a855f7; color: #6b21a8; padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: 800; }

        .alert-banner-danger {
            background: #fef2f2;
            border: 1px solid #f87171;
            border-radius: 6px;
            padding: 12px 14px;
            color: #991b1b;
            margin-top: 12px;
            text-align: center;
        }
        .alert-banner-safe {
            background: #f0fdf4;
            border: 1px solid #4ade80;
            border-radius: 6px;
            padding: 10px 12px;
            color: #166534;
            margin-top: 12px;
            text-align: center;
            font-weight: 700;
            font-size: 13px;
        }

        div[data-testid="stMetricValue"] {
            font-size: 20px !important;
            color: #0284c7 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# HARDWARE WIRELESS WI-FI & USB SERIAL TELEMETRY BRIDGE
# -----------------------------------------------------------------------------
import threading
import re
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import serial
    import json
except ImportError:
    serial = None

# Global thread-safe cache for hardware telemetry
HARDWARE_TELEMETRY_CACHE = {}

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

class TelemetryHTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path in ["/api/telemetry", "/"]:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode('utf-8'))
                src_id = int(data.get("src_node", 1))
                HARDWARE_TELEMETRY_CACHE[src_id] = {
                    "battery": float(data.get("battery_pct", 95.0)),
                    "temperature": float(data.get("temperature_c", 28.5)),
                    "air_quality_pm25": float(data.get("pm25_ugm3", 15.0)),
                    "water_level": float(data.get("water_level_cm", 0.0)),
                    "status": "HARDWARE LIVE (WIFI) 🟢",
                    "role": data.get("role", "Hardware Cluster Head 👑"),
                    "risk_score": float(data.get("risk_score", 0.05)),
                    "last_seen": time.time()
                }
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            except Exception:
                pass
        self.send_response(400)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def _background_wifi_server_worker():
    try:
        server = HTTPServer(('0.0.0.0', 8080), TelemetryHTTPHandler)
        server.serve_forever()
    except Exception:
        pass

def _background_hardware_worker():
    # Serial COM port polling disabled to ensure COM3/COM4 are 100% unlocked for Arduino IDE flashing.
    # Telemetry is received wirelessly over Wi-Fi HTTP POST (Port 8080).
    pass

# Start background threads once
if "hw_thread_started" not in st.session_state:
    st.session_state.hw_thread_started = True
    wifi_thread = threading.Thread(target=_background_wifi_server_worker, daemon=True)
    wifi_thread.start()
    hw_thread = threading.Thread(target=_background_hardware_worker, daemon=True)
    hw_thread.start()

def apply_hardware_telemetry(world: WorldSimulation):
    now = time.time()
    for node in world.nodes:
        node.is_hardware = False

    for src_id, data in list(HARDWARE_TELEMETRY_CACHE.items()):
        if now - data.get("last_seen", 0) < 15.0:  # Active within last 15s
            node = world.get_node(src_id)
            if node:
                node.is_hardware = True
                if "battery" in data: node.battery = data["battery"]
                if "water_level" in data: node.sensors.water_level = data["water_level"]
                if "temperature" in data: node.sensors.temperature = data["temperature"]
                if "air_quality_pm25" in data: node.sensors.air_quality_pm25 = data["air_quality_pm25"]
                node.status = "⚡ HARDWARE LIVE (WiFi)"
                if "role" in data:
                    role_str = str(data["role"])
                    if "CH" in role_str:
                        node.role = "Hardware Cluster Head 👑"
                        node.is_ch = True
                    else:
                        node.role = "Hardware Member"
                        node.is_ch = False

# -----------------------------------------------------------------------------
# INITIALIZE SESSION STATE
# -----------------------------------------------------------------------------
def get_world() -> WorldSimulation:
    if "world" not in st.session_state:
        st.session_state.world = init_world()
        leach_elect_clusters(st.session_state.world, target_chs=4)
        run_multi_node_consensus(st.session_state.world)
    return st.session_state.world


world = get_world()

# -----------------------------------------------------------------------------
# STEP SIMULATION
# -----------------------------------------------------------------------------
if world.running:
    update_sensors_step(world)
    consume_energy_step(world)
    run_multi_node_consensus(world)

apply_hardware_telemetry(world)

# -----------------------------------------------------------------------------
# TOP HEADER BAR
# -----------------------------------------------------------------------------
scenario_icons = {
    "NORMAL": "Normal Environment",
    "WILDFIRE": "Wildfire Hazard",
    "FLOOD": "Flood Hazard",
    "GAS LEAK": "Gas Leak Hazard",
    "LANDSLIDE": "Landslide Hazard",
    "SENSOR FAILURE": "Sensor Failure",
    "COMMUNICATION FAILURE": "Communication Failure",
    "LOW BATTERY": "Low Battery",
}

hcol1, hcol2, hcol3, hcol4, hcol5, hcol6 = st.columns([2.6, 1.4, 0.8, 0.8, 1.0, 1.4])

with hcol1:
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:8px;">
            <div>
                <div style="font-family: 'Outfit', 'Plus Jakarta Sans', sans-serif; font-size: 28px; font-weight: 900; color: #0f172a; line-height: 1.0; letter-spacing: 1.5px;">
                    ENVIRON<span style="color:#0284c7;">-X</span>
                </div>
                <div style="font-family: 'Inter', sans-serif; font-size: 10.5px; color: #059669; font-weight: 800; letter-spacing: 0.8px; margin-top: 2px;">
                    ENVIRONMENTAL INTELLIGENCE NETWORK
                </div>
            </div>
            <div class="hdr-badge">SYSTEM ONLINE</div>
            {f'<div style="font-size:10px; background:#ecfdf5; border:1px solid #6ee7b7; color:#047857; padding:3px 8px; border-radius:4px; font-weight:800;">⚡ PHYSICAL HARDWARE ONLINE ({sum(1 for n in world.nodes if getattr(n, "is_hardware", False))})</div>' if any(getattr(n, "is_hardware", False) for n in world.nodes) else '<div style="font-size:10px; background:#f8fafc; border:1px solid #cbd5e1; color:#64748b; padding:3px 7px; border-radius:4px; font-weight:700;">⚙️ SIMULATION MODE</div>'}
            <div style="font-size:10px; background:#f0f9ff; border:1px solid #bae6fd; color:#0284c7; padding:3px 7px; border-radius:4px; font-weight:700;">
                📶 Wi-Fi: http://{LOCAL_IP}:8080/api/telemetry
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with hcol2:
    selected_scen = st.selectbox(
        "Scenario",
        options=list(scenario_icons.keys()),
        format_func=lambda k: scenario_icons[k],
        index=list(scenario_icons.keys()).index(world.scenario),
        key="scen_select",
        label_visibility="collapsed",
    )
    if selected_scen != world.scenario:
        world.scenario = selected_scen
        world.scenario_start_step = world.step_count
        world._last_logged_confirm_cnt = -1
        world._current_scenario_tracker = selected_scen
        world.intensity = 0.1 if selected_scen != "NORMAL" else 0.0
        if selected_scen == "WILDFIRE":
            world.selected_node_id = 7  # N07 in Forest Zone
        elif selected_scen == "FLOOD":
            world.selected_node_id = 11  # N11 in River / Floody Zone
        elif selected_scen == "GAS LEAK":
            world.selected_node_id = 8  # N08 in Industrial Gas Zone
        elif selected_scen == "LANDSLIDE":
            world.selected_node_id = 9  # N09 in Hilly Slope Zone

        scen_node = world.get_node(world.selected_node_id)
        if scen_node:
            st.session_state["node_select_box"] = scen_node.name

        if selected_scen == "SENSOR FAILURE":
            world.get_node(7).failed = True
            add_log(world, "FAULT INJECT", "Node-07 hardware failure injected.", level="WARNING")
        else:
            for n in world.nodes:
                n.failed = False

        update_sensors_step(world)
        run_multi_node_consensus(world)
        add_log(world, "SCENARIO CHANGE", f"Simulation scenario changed to {selected_scen}.")


with hcol3:
    if st.button("Pause" if world.running else "Start", use_container_width=True):
        world.running = not world.running
        st.rerun()

with hcol4:
    if st.button("Next Round", use_container_width=True):
        leach_elect_clusters(world, target_chs=4)
        st.rerun()

with hcol5:
    if st.button("Reset", use_container_width=True):
        st.session_state.world = init_world()
        st.rerun()

with hcol6:
    fb_status = {"connected": False, "pending_queue_count": 0}
    try:
        import firebase_service
        fb_status = firebase_service.get_firebase_status()
    except Exception:
        pass

    if fb_status["connected"]:
        fb_badge = '<span style="color:#059669; font-weight:800;">Firebase: Connected</span>'
    else:
        fb_badge = f'<span style="color:#d97706; font-weight:800;">Firebase: Offline ({fb_status["pending_queue_count"]} Q)</span>'

    st.markdown(
        f"""
        <div style="text-align:right; font-size:12px; color:#64748b; font-weight:700;">
            <div>Round: <b style="color:#0284c7;">{world.round_num}</b> &nbsp;|&nbsp; {fb_badge}</div>
            <div>Gateway: <b style="color:#059669;">Online</b> &nbsp;|&nbsp; Time: <b style="color:#0f172a;">{world.sim_clock.strftime('%H:%M:%S')}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown("<div style='height:2px;'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# MAIN BODY TOP ROW (MAP | NODE INFO | EDGE AI)
# -----------------------------------------------------------------------------
col_map, col_node, col_ai = st.columns([1.55, 0.95, 1.0])

# COLUMN 1: INTERACTIVE GEOGRAPHIC MESH MAP
with col_map:
    st.markdown(
        """
        <div class="card-hdr">
            <span>Network Map (LEACH Mesh)</span>
            <span style="font-size:12px; color:#64748b; font-weight:600;">Simulated Deployment Area</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c_state = world.consensus_state
    seed_nid = c_state.get("seed_nid", 7 if world.scenario == "WILDFIRE" else (11 if world.scenario == "FLOOD" else (8 if world.scenario == "GAS LEAK" else (9 if world.scenario == "LANDSLIDE" else None))))
    confirming_names = c_state.get("affected_nodes", [])

    map_data = []
    for n in world.nodes:
        ai_res = evaluate_edge_ai(n, world.scenario)
        haz = ai_res["hazard"]
        conf = ai_res["confidence"]

        if n.failed:
            color = [100, 116, 139, 200]
            status_lbl = "Offline (Fault)"
        elif n.solar_recharging:
            color = [56, 189, 248, 255]  # Cyan for Solar Recharging
            status_lbl = "Solar Recharging"
        elif n.nid == seed_nid and world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
            # ONLY the primary epicenter node gets RED color
            color = [239, 68, 68, 255]
            status_lbl = f"CRITICAL HAZARD ({world.scenario})"
        elif world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"] and n.name in confirming_names:
            # ONLY confirmed direct neighbor nodes turn YELLOW step-by-step
            color = [245, 158, 11, 255]
            status_lbl = f"Confirming Neighbor ({world.scenario})"
        elif n.is_ch:
            color = [168, 85, 247, 255]
            status_lbl = "Cluster Head"
        else:
            color = [16, 185, 129, 255]
            status_lbl = "Normal"

        fmt = n.get_formatted_sensors()
        if n.zone == "River / Floody Zone":
            s1_l, s1_v = "Water Level", fmt["water"]
            s2_l, s2_v = "River Flow Rate", fmt["flow"]
            s3_l, s3_v = "Soil Moisture", fmt["soil"]
            s4_l, s4_v = "Humidity", fmt["humidity"]
        elif n.zone == "Hilly Slope Zone":
            s1_l, s1_v = "3-Axis Tilt", fmt["tilt"]
            s2_l, s2_v = "Ground Vibration", fmt["vibration"]
            s3_l, s3_v = "IMU Motion", fmt["motion"]
            s4_l, s4_v = "Soil Saturation", fmt["soil"]
        else:
            s1_l, s1_v = "Temperature", fmt["temp"]
            s2_l, s2_v = "PM2.5 Dust", fmt["pm25"]
            s3_l, s3_v = "Gas (VOC)", fmt["gas"]
            s4_l, s4_v = "Smoke / CO2", fmt["smoke"]

        map_data.append({
            "nid": n.nid,
            "name": n.name,
            "zone": f"{n.zone}",
            "elev": n.elevation,
            "role": "Cluster Head (CH)" if n.is_ch else f"Member (CH-{n.cluster_id:02d})",
            "lat": n.lat,
            "lon": n.lon,
            "status": status_lbl,
            "battery": int(n.battery),
            "s1_l": s1_l, "s1_v": s1_v,
            "s2_l": s2_l, "s2_v": s2_v,
            "s3_l": s3_l, "s3_v": s3_v,
            "s4_l": s4_l, "s4_v": s4_v,
            "color": color,
            "radius": 140 if n.is_ch else 90,
        })

    df_nodes = pd.DataFrame(map_data)

    gw = world.gateway
    df_gw = pd.DataFrame([{
        "name": "GW-01 (Gateway)",
        "zone": "Central Gateway Station",
        "role": "Gateway Unit",
        "status": "Online",
        "battery": 100,
        "s1_l": "Uplink Protocol", "s1_v": "LoRaWAN 868 MHz",
        "s2_l": "Signal Strength", "s2_v": "-68 dBm (Strong)",
        "s3_l": "Connected Nodes", "s3_v": "12 / 12 Active",
        "s4_l": "Network Latency", "s4_v": "12 ms",
        "lat": gw["lat"],
        "lon": gw["lon"],
        "color": [56, 189, 248, 255],
        "radius": 180,
    }])

    hazard_circles = []
    if world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        epic_lat, epic_lon = (28.6040, 77.1720) if world.scenario == "WILDFIRE" else ((28.6080, 77.2500) if world.scenario == "FLOOD" else ((28.6220, 77.2180) if world.scenario == "GAS LEAK" else (28.5950, 77.1950)))
        h_color = [239, 68, 68, 80] if world.scenario in ["WILDFIRE", "GAS LEAK"] else ([56, 189, 248, 80] if world.scenario == "FLOOD" else [168, 85, 247, 80])
        hazard_circles.append({
            "lat": epic_lat,
            "lon": epic_lon,
            "radius": 450 * max(0.4, world.intensity),
            "color": h_color,
        })
    df_hazard = pd.DataFrame(hazard_circles)

    line_data = []
    # 1. Base inter-node mesh topology links
    for src_id, dst_id in get_inter_node_links():
        src_n = world.get_node(src_id)
        dst_n = world.get_node(dst_id)
        if not src_n.failed and not dst_n.failed:
            line_data.append({
                "start": [src_n.lon, src_n.lat],
                "end": [dst_n.lon, dst_n.lat],
                "color": [148, 163, 184, 120],
                "width": 1.2,
            })

    # 2. Member Node ➔ Assigned Cluster Head data flow links (Green)
    for n in world.nodes:
        if not n.failed and not n.is_ch:
            ch_node = world.get_node(n.cluster_id)
            if not ch_node.failed:
                line_data.append({
                    "start": [n.lon, n.lat],
                    "end": [ch_node.lon, ch_node.lat],
                    "color": [16, 185, 129, 200],
                    "width": 2.2,
                })

    # 3. Cluster Head ➔ Gateway GW-01 aggregate data links (Cyan)
    for n in world.nodes:
        if n.is_ch and not n.failed:
            line_data.append({
                "start": [n.lon, n.lat],
                "end": [gw["lon"], gw["lat"]],
                "color": [2, 132, 199, 240],
                "width": 3.8,
            })
            
    df_lines = pd.DataFrame(line_data)

    # 4. Animated Data Packets Flowing Simultaneously Live
    packet_dots = []
    step_t = world.step_count

    # Member ➔ Cluster Head Packet Flow (Simultaneous streaming green dots)
    for n in world.nodes:
        if not n.failed and not n.is_ch:
            ch_node = world.get_node(n.cluster_id)
            if not ch_node.failed:
                for offset in [0.0, 0.5]:
                    prog = ((step_t * 0.18) + (n.nid * 0.15) + offset) % 1.0
                    p_lat = n.lat + (ch_node.lat - n.lat) * prog
                    p_lon = n.lon + (ch_node.lon - n.lon) * prog
                    packet_dots.append({
                        "name": f"Sensor Data Flow (N{n.nid:02d} ➔ CH-{ch_node.nid:02d})",
                        "zone": "Member ➔ CH Data Stream",
                        "role": "Telemetry Packet",
                        "status": "Transmitting",
                        "battery": int(n.battery),
                        "s1_l": "Source Node", "s1_v": n.name,
                        "s2_l": "Target Cluster Head", "s2_v": f"CH-{ch_node.nid:02d}",
                        "s3_l": "Payload Size", "s3_v": "64 Bytes",
                        "s4_l": "Link Protocol", "s4_v": "LoRa Mesh",
                        "lat": p_lat,
                        "lon": p_lon,
                        "color": [16, 185, 129, 255],
                        "radius": 35,
                    })

    # Cluster Head ➔ Gateway GW-01 Packet Flow (Simultaneous streaming cyan dots)
    for n in world.nodes:
        if n.is_ch and not n.failed:
            for offset in [0.0, 0.5]:
                prog = ((step_t * 0.22) + (n.nid * 0.20) + offset) % 1.0
                p_lat = n.lat + (gw["lat"] - n.lat) * prog
                p_lon = n.lon + (gw["lon"] - n.lon) * prog
                packet_dots.append({
                    "name": f"Aggregate Telemetry Flow (CH-{n.nid:02d} ➔ GW-01)",
                    "zone": "CH ➔ Gateway Uplink",
                    "role": "Aggregate Payload",
                    "status": "Transmitting",
                    "battery": int(n.battery),
                    "s1_l": "Cluster Head", "s1_v": f"CH-{n.nid:02d}",
                    "s2_l": "Target Gateway", "s2_v": "GW-01",
                    "s3_l": "Payload Size", "s3_v": "256 Bytes",
                    "s4_l": "Link Protocol", "s4_v": "LoRaWAN Uplink",
                    "lat": p_lat,
                    "lon": p_lon,
                    "color": [2, 132, 199, 255],
                    "radius": 45,
                })

    # Emergency Alert & Neighbor Verification Packet Flows during active scenario
    if world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        epic_nid = 7 if world.scenario == "WILDFIRE" else (11 if world.scenario == "FLOOD" else (8 if world.scenario == "GAS LEAK" else 9))
        epic_n = world.get_node(epic_nid)
        ch_n = world.get_node(epic_n.cluster_id)
        
        pending_names = c_state.get("pending_nodes", [])

        # 1. Pre-Confirmation Data Flow: Red Epicenter Node ➔ Pending Neighbor Nodes
        for p_name in pending_names:
            p_node = next((n for n in world.nodes if n.name == p_name), None)
            if p_node:
                for offset in [0.0, 0.5]:
                    prog = ((step_t * 0.25) + offset) % 1.0
                    packet_dots.append({
                        "name": f"Pre-Confirmation Hazard Stream ({epic_n.name} ➔ {p_node.name})",
                        "zone": "Epicenter Broadcast",
                        "role": "Verification Signal",
                        "status": "Transmitting to Neighbor",
                        "battery": int(epic_n.battery),
                        "s1_l": "Epicenter Node", "s1_v": epic_n.name,
                        "s2_l": "Pending Neighbor", "s2_v": p_node.name,
                        "s3_l": "State", "s3_v": "Awaiting Consensus",
                        "s4_l": "Signal Type", "s4_v": "Hazard Broadcast",
                        "lat": epic_n.lat + (p_node.lat - epic_n.lat) * prog,
                        "lon": epic_n.lon + (p_node.lon - epic_n.lon) * prog,
                        "color": [245, 158, 11, 255],
                        "radius": 40,
                    })

        # 2. Confirmed Consensus Alert Flow: Member ➔ Cluster Head ➔ Gateway
        if c_state.get("confirmed", False):
            for offset in [0.0, 0.5]:
                # Step 1: Epicenter ➔ CH
                prog1 = ((step_t * 0.28) + offset) % 1.0
                packet_dots.append({
                    "name": f"Emergency Alert Flow ({epic_n.name} ➔ CH-{ch_n.nid:02d})",
                    "zone": "Emergency Priority Channel",
                    "role": "Hazard Alert Packet",
                    "status": "CRITICAL TRANSMISSION",
                    "battery": int(epic_n.battery),
                    "s1_l": "Epicenter Node", "s1_v": epic_n.name,
                    "s2_l": "Hazard Event", "s2_v": world.scenario,
                    "s3_l": "Transmission Step", "s3_v": f"{epic_n.name} ➔ CH-{ch_n.nid:02d}",
                    "s4_l": "Priority Level", "s4_v": "HIGH PRIORITY",
                    "lat": epic_n.lat + (ch_n.lat - epic_n.lat) * prog1,
                    "lon": epic_n.lon + (ch_n.lon - epic_n.lon) * prog1,
                    "color": [239, 68, 68, 255],
                    "radius": 70,
                })
                # Step 2: CH ➔ Gateway
                prog2 = ((step_t * 0.28) + 0.33 + offset) % 1.0
                packet_dots.append({
                    "name": f"Emergency Alert Flow (CH-{ch_n.nid:02d} ➔ GW-01)",
                    "zone": "Emergency Gateway Uplink",
                    "role": "Hazard Alert Packet",
                    "status": "CRITICAL TRANSMISSION",
                    "battery": int(ch_n.battery),
                    "s1_l": "Aggregating CH", "s1_v": f"CH-{ch_n.nid:02d}",
                    "s2_l": "Hazard Event", "s2_v": world.scenario,
                    "s3_l": "Transmission Step", "s3_v": f"CH-{ch_n.nid:02d} ➔ GW-01",
                    "s4_l": "Priority Level", "s4_v": "HIGH PRIORITY",
                    "lat": ch_n.lat + (gw["lat"] - ch_n.lat) * prog2,
                    "lon": ch_n.lon + (gw["lon"] - ch_n.lon) * prog2,
                    "color": [239, 68, 68, 255],
                    "radius": 70,
                })

    df_packets = pd.DataFrame(packet_dots)

    layer_sat = pdk.Layer(
        "TileLayer",
        data="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        min_zoom=0,
        max_zoom=19,
        tile_size=256,
    )

    layer_mesh = pdk.Layer("LineLayer", df_lines, get_source_position="start", get_target_position="end", get_color="color", get_width="width")
    layer_packets = pdk.Layer("ScatterplotLayer", df_packets, get_position=["lon", "lat"], get_color="color", get_radius="radius", pickable=True) if not df_packets.empty else None
    layer_hazard = pdk.Layer("ScatterplotLayer", df_hazard, get_position=["lon", "lat"], get_color="color", get_radius="radius", pickable=False) if not df_hazard.empty else None
    layer_nodes = pdk.Layer("ScatterplotLayer", df_nodes, get_position=["lon", "lat"], get_color="color", get_radius="radius", pickable=True)
    layer_gw = pdk.Layer("ScatterplotLayer", df_gw, get_position=["lon", "lat"], get_color="color", get_radius="radius", pickable=True)
    layer_text = pdk.Layer("TextLayer", df_nodes, get_position=["lon", "lat"], get_text="name", get_size=15, get_color=[15, 23, 42, 255], get_alignment_baseline="'bottom'")

    view_state = pdk.ViewState(latitude=28.6140, longitude=77.2150, zoom=12.5, pitch=30)
    layers = [layer_mesh]
    if layer_packets:
        layers.append(layer_packets)
    layers.extend([layer_nodes, layer_gw, layer_text])
    if layer_hazard:
        layers.insert(1, layer_hazard)

    deck = pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        map_style="https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
        tooltip={
            "html": """
            <div style="font-family: 'Inter', system-ui, sans-serif; padding: 10px 14px; background: rgba(255, 255, 255, 0.96); color: #0f172a; border: 1px solid #cbd5e1; border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15); font-size: 12px; min-width: 220px;">
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px; margin-bottom: 6px;">
                    <span style="font-size: 16px; font-weight: 800; color: #0284c7;">{name}</span>
                    <span style="font-size: 11px; color: #64748b; font-weight:700;">{zone}</span>
                </div>
                <div style="margin-bottom: 6px; font-size: 11.5px; color: #334155;">
                    <div>Status: <b style="color:#059669;">{status}</b></div>
                    <div>Role: <b style="color:#0284c7;">{role}</b></div>
                    <div>Battery Level: <b style="color:#0284c7;">{battery}%</b></div>
                </div>
                <div style="border-top: 1px solid #e2e8f0; padding-top: 6px; line-height: 1.6;">
                    <div style="font-size: 11.5px; font-weight: 800; color: #0284c7; margin-bottom: 3px;">Live Sensor Readings:</div>
                    <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">{s1_l}:</span> <b style="color:#0f172a; font-family:monospace;">{s1_v}</b></div>
                    <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">{s2_l}:</span> <b style="color:#0f172a; font-family:monospace;">{s2_v}</b></div>
                    <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">{s3_l}:</span> <b style="color:#0f172a; font-family:monospace;">{s3_v}</b></div>
                    <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">{s4_l}:</span> <b style="color:#0f172a; font-family:monospace;">{s4_v}</b></div>
                </div>
            </div>
            """,
            "style": {
                "backgroundColor": "transparent",
                "color": "#0f172a",
                "padding": "0px",
                "boxShadow": "none",
            },
        },
    )

    st.pydeck_chart(deck, height=515)

    st.markdown(
        """
        <div style="display:flex; justify-content:space-between; align-items:center; background:#f1f5f9; padding:6px 12px; border-radius:6px; font-size:11.5px; font-weight:600; border:1px solid #e2e8f0; color:#334155;">
            <span><span style="display:inline-block; width:9px; height:9px; background:#ef4444; border-radius:50%; margin-right:4px;"></span> Epicenter Hazard</span>
            <span><span style="display:inline-block; width:9px; height:9px; background:#f59e0b; border-radius:50%; margin-right:4px;"></span> Confirming Neighbor</span>
            <span><span style="display:inline-block; width:9px; height:9px; background:#10b981; border-radius:50%; margin-right:4px;"></span> Member Node</span>
            <span><span style="display:inline-block; width:9px; height:9px; background:#a855f7; border-radius:50%; margin-right:4px;"></span> Cluster Head (CH)</span>
            <span><span style="color:#059669; font-weight:bold;">—</span> Member to CH Stream</span>
            <span><span style="color:#0284c7; font-weight:bold;">—</span> CH to Gateway Stream</span>
            <span><span style="display:inline-block; width:9px; height:9px; background:#0284c7; border-radius:50%; margin-right:4px;"></span> Gateway (GW-01)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

# COLUMN 2: SELECTED NODE INFORMATION PANEL
with col_node:
    st.markdown("<div class='card-hdr'><span>Node Information</span></div>", unsafe_allow_html=True)

    node_options = [
        f"{n.name} ⚡ (PHYSICAL HARDWARE ONLINE)" if getattr(n, "is_hardware", False) else f"{n.name} (Simulated Fallback)"
        for n in world.nodes
    ]
    
    # Auto-select hardware node if online and user hasn't selected another
    hw_nodes = [n for n in world.nodes if getattr(n, "is_hardware", False)]
    if "node_select_box" not in st.session_state or st.session_state["node_select_box"] not in node_options:
        if hw_nodes:
            st.session_state["node_select_box"] = f"{hw_nodes[0].name} ⚡ (PHYSICAL HARDWARE ONLINE)"
        else:
            st.session_state["node_select_box"] = node_options[0]

    selected_name = st.selectbox(
        "Select Node to Inspect",
        options=node_options,
        key="node_select_box",
    )
    try:
        raw_prefix = selected_name.split(" ")[0].split("-")[0]
        nid = int(raw_prefix.replace("N", "").strip())
    except Exception:
        nid = world.selected_node_id
    sel_node = world.get_node(nid)
    world.selected_node_id = sel_node.nid

    ai_info = evaluate_edge_ai(sel_node, world.scenario)

    batt_color = "#0284c7" if sel_node.solar_recharging else ("#059669" if sel_node.battery > 50 else ("#d97706" if sel_node.battery > 25 else "#dc2626"))
    status_bg = "#0284c7" if sel_node.solar_recharging else ("#dc2626" if "CRITICAL" in sel_node.status else ("#d97706" if "Anomaly" in sel_node.status else "#059669"))
    zone_cls = "zone-badge-river" if "River" in sel_node.zone else ("zone-badge-slope" if "Hilly" in sel_node.zone else "zone-badge-forest")

    is_hw = getattr(sel_node, "is_hardware", False)
    if is_hw:
        hw_banner = """<div style="background:#ecfdf5; border:1px solid #6ee7b7; color:#047857; font-size:12px; font-weight:800; padding:6px 10px; border-radius:6px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;"><span>⚡ PHYSICAL HARDWARE NODE (ESP32)</span><span style="font-size:10.5px; background:#10b981; color:white; padding:2px 7px; border-radius:4px; font-weight:800;">LIVE WI-FI / LORA</span></div>"""
    else:
        hw_banner = """<div style="background:#f8fafc; border:1px solid #cbd5e1; color:#64748b; font-size:11.5px; font-weight:700; padding:5px 10px; border-radius:6px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;"><span>⚙️ SIMULATED FALLBACK NODE</span><span style="font-size:10px; background:#e2e8f0; color:#475569; padding:2px 6px; border-radius:4px; font-weight:700;">DIGITAL TWIN ENGINE</span></div>"""

    st.markdown(
        f"""<div style="background:#ffffff; padding:12px; border-radius:6px; border:1px solid #e2e8f0; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
{hw_banner}
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px;">
<div><b style="font-size:17px; color:#0f172a;">{sel_node.name}</b> &nbsp;<span class="{zone_cls}">{sel_node.zone}</span></div>
<span style="background:{status_bg}; color:#fff; font-size:11px; font-weight:800; padding:2px 8px; border-radius:10px;">{sel_node.status}</span>
</div>
<div style="font-size:12px; color:#64748b; margin-top:5px;">Role: <b style="color:#0284c7;">{'Cluster Head (GW Connected)' if sel_node.is_ch else 'Cluster Member (CH-0' + str(sel_node.cluster_id) + ')'}</b> &nbsp;|&nbsp; Elev: <b style="color:#0f172a;">{sel_node.elevation}</b></div>
<div style="font-size:11.5px; color:#64748b; margin-top:3px;">Sensors: {', '.join(sel_node.sensor_suite)}</div>
<div style="margin-top:8px;">
<div style="display:flex; justify-content:space-between; font-size:12px; color:#64748b; font-weight:600;"><span>Battery Level</span><b style="color:{batt_color};">{int(sel_node.battery)}% {'(Solar)' if sel_node.solar_recharging else ''}</b></div>
<div style="width:100%; height:7px; background:#e2e8f0; border-radius:4px; overflow:hidden; margin-top:3px;"><div style="width:{int(sel_node.battery)}%; height:100%; background:{batt_color}; border-radius:4px;"></div></div>
</div>
</div>""",
        unsafe_allow_html=True,
    )

    fmt = sel_node.get_formatted_sensors()
    s = sel_node.sensors
    pm_val_num = getattr(s, "air_quality_pm25", 18.5)
    if is_hw:
        wl_display_cm = s.water_level * 100.0 if s.water_level < 2.0 else s.water_level
        readings = [
            ("Water Level (Physical)", f"{wl_display_cm:.1f} cm", "↑" if wl_display_cm > 15.0 else "ok"),
            ("Temperature (Physical)", fmt["temp"], "↑" if s.temperature > 35 else "ok"),
            ("Air Quality PM2.5 (Physical)", fmt["pm25"], "↑" if pm_val_num > 35 else "ok"),
            ("Battery Level (Physical)", f"{int(sel_node.battery)} %", "dn" if sel_node.battery < 25 else "ok"),
            ("Hazard Risk Score", f"{getattr(sel_node, 'risk_score', 0.05):.2f}", "↑" if getattr(sel_node, 'risk_score', 0.05) > 0.5 else "ok"),
        ]
    elif sel_node.zone == "River / Floody Zone":
        readings = [
            ("Water Level", fmt["water"], "↑" if s.water_level > 1.4 else "ok"),
            ("River Flow Rate", fmt["flow"], "↑" if s.flow_rate > 2.5 else "ok"),
            ("Soil Moisture", fmt["soil"], "↑" if s.soil_moisture > 75 else "ok"),
            ("Air Quality (PM2.5)", fmt["pm25"], "↑" if pm_val_num > 35 else "ok"),
            ("Solar Irradiance", fmt["solar"], "ok"),
        ]
    elif sel_node.zone == "Hilly Slope Zone":
        readings = [
            ("3-Axis Tilt", fmt["tilt"], "↑" if s.tilt > 2.5 else "ok"),
            ("Ground Vibration", fmt["vibration"], "↑" if s.vibration > 1.8 else "ok"),
            ("IMU Motion", fmt["motion"], "↑" if s.motion > 1.2 else "ok"),
            ("Air Quality (PM2.5)", fmt["pm25"], "↑" if pm_val_num > 35 else "ok"),
            ("Solar Irradiance", fmt["solar"], "ok"),
        ]
    else:  # Forest Zone
        readings = [
            ("Temperature", fmt["temp"], "↑" if s.temperature > 32 else "ok"),
            ("Air Quality (PM2.5)", fmt["pm25"], "↑" if pm_val_num > 35 else "ok"),
            ("Smoke / CO2", fmt["smoke"], "↑" if s.smoke > 30 else "ok"),
            ("Gas (VOC)", fmt["gas"], "↑" if s.gas > 150 else "ok"),
            ("Solar Irradiance", fmt["solar"], "ok"),
        ]

    st.markdown("<div style='font-size:14.5px; font-weight:800; color:#0284c7; margin-bottom:6px;'>Active Zone Sensor Suite</div>", unsafe_allow_html=True)
    for lbl, val, trend in readings:
        trend_html = "<span class='trend-up'>HIGH</span>" if trend == "↑" else ("<span class='trend-dn'>LOW</span>" if trend == "↓" else "<span class='trend-ok'>NORMAL</span>")
        st.markdown(
            f"""
            <div class="sensor-row">
                <span class="sensor-label">{lbl}</span>
                <span><span class="sensor-val">{val}</span> {trend_html}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

# COLUMN 3: EDGE AI INFERENCE & DECISION PANEL
with col_ai:
    c_state = world.consensus_state
    seed_nid = c_state.get("seed_nid", 7 if world.scenario == "WILDFIRE" else (11 if world.scenario == "FLOOD" else (8 if world.scenario == "GAS LEAK" else (9 if world.scenario == "LANDSLIDE" else None))))

    st.markdown(f"<div class='card-hdr'><span>Edge AI Inference ({sel_node.name})</span></div>", unsafe_allow_html=True)
    st.caption(f"Model: {sel_node.zone} Multi-Hazard TinyML")

    if seed_nid and sel_node.nid != seed_nid and world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        epic_node = world.get_node(seed_nid)
        epic_ai = evaluate_edge_ai(epic_node, world.scenario)

        epic_conf = int(epic_ai.get("confidence", 0.95) * 100)
        st.markdown(
            f"""
            <div style="background:#f0f9ff; border:1px solid #bae6fd; border-radius:4px; padding:5px 9px; font-size:11px; font-weight:600; color:#0369a1; margin-bottom:6px;">
                Active Event: <b>{world.scenario}</b> at Epicenter <b>{epic_node.name}</b> ({epic_conf}% Confidence)
            </div>
            """,
            unsafe_allow_html=True,
        )

    probs = ai_info["probs"]

    for hazard_name, prob_val in sorted(probs.items(), key=lambda kv: kv[1], reverse=True):
        pct = int(prob_val * 100)
        p_color = "#dc2626" if hazard_name == "Wildfire" else ("#0284c7" if hazard_name == "Gas Leak" else ("#0284c7" if hazard_name == "Flood" else ("#9333ea" if hazard_name == "Landslide" else "#059669")))
        st.markdown(
            f"""
            <div style="font-size:12px; margin-bottom:5px;">
                <div style="display:flex; justify-content:space-between;">
                    <span style="color:#334155; font-weight:700;">{hazard_name}</span>
                    <b style="color:{p_color}; font-size:12.5px;">{pct}%</b>
                </div>
                <div style="width:100%; height:7px; background:#e2e8f0; border-radius:4px; overflow:hidden; margin-top:2px;">
                    <div style="width:{pct}%; height:100%; background:{p_color}; border-radius:4px;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='font-size:14px; font-weight:800; color:#059669; margin-top:10px; margin-bottom:4px;'>Zone Safety Threshold Check</div>", unsafe_allow_html=True)
    t_hits = ai_info["hits"]
    st.markdown(
        f"""
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px 12px; font-size:12px;">
            <div style="color:#334155; font-weight:600;">Zone Thresholds Exceeded: <b style="color:{'#dc2626' if t_hits > 0 else '#059669'}; font-size:13px;">{t_hits} / 4</b></div>
            <div style="color:#64748b; font-size:11px;">Tailored to {sel_node.zone} sensor parameters.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c_state = world.consensus_state
    c_status = c_state.get("status", "IDLE")
    agree_cnt = c_state.get("agree_count", 0)
    tot_cnt = c_state.get("total_nodes", 5)
    aff_nodes = c_state.get("affected_nodes", [])

    st.markdown(f"<div style='font-size:14px; font-weight:800; color:#0284c7; margin-top:10px;'>Neighbor Node Consensus ({agree_cnt}/{tot_cnt} Direct Neighbors Agree)</div>", unsafe_allow_html=True)

    dots_html = ""
    for i in range(tot_cnt):
        d_color = "#d97706" if i < agree_cnt else "#cbd5e1"
        dots_html += f"<div style='width:13px; height:13px; border-radius:50%; background:{d_color}; display:inline-block; margin-right:6px;'></div>"

    st.markdown(f"<div style='margin-top:5px;'>{dots_html}</div>", unsafe_allow_html=True)

    seq_items = c_state.get("neighbor_sequence", [])
    if seq_items:
        seq_html = "<div style='display:flex; flex-wrap:wrap; gap:5px; margin-top:6px; font-size:11px;'>"
        for item in seq_items:
            if item["confirmed"]:
                seq_html += f"<span style='background:#fef3c7; border:1px solid #f59e0b; color:#b45309; padding:3px 7px; border-radius:4px; font-weight:800;'>{item['order']} Neighbor: {item['node']}</span>"
            else:
                seq_html += f"<span style='background:#f1f5f9; border:1px dashed #94a3b8; color:#64748b; padding:3px 7px; border-radius:4px; font-weight:600;'>{item['order']} Neighbor: {item['node']} (Pending)</span>"
        seq_html += "</div>"
        st.markdown(seq_html, unsafe_allow_html=True)
    elif aff_nodes:
        st.markdown(f"<div style='font-size:11px; color:#64748b; margin-top:2px;'>Confirming Neighbors: <b style='color:#059669;'>{', '.join(aff_nodes)}</b></div>", unsafe_allow_html=True)

    if world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"] and c_state.get("confirmed", False):
        haz_label = c_state.get("hazard", "HAZARD")
        conf_pct = int(c_state.get("confidence", 0.92) * 100)
        st.markdown(
            f"""
            <div class="alert-banner-danger">
                <div style="font-size:15px; font-weight:800; color:#991b1b;">Hazard Confirmed by Neighbors: {haz_label.upper()}</div>
                <div style="font-size:12px; margin-top:3px; color:#7f1d1d; font-weight:600;">Confidence: <b>{conf_pct}%</b> | Consensus: <b>{agree_cnt}/{tot_cnt} Direct Neighbors</b></div>
                <div style="font-size:11px; color:#0284c7; margin-top:4px; font-weight:700;">Routing alert packet: Member Node ➔ Cluster Head ➔ Gateway (GW-01)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        if world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
            maj_thresh = math.ceil(tot_cnt / 2.0)
            st.markdown(
                f"""
                <div class="alert-banner-safe" style="border-color:#fcd34d; color:#92400e; background:#fffbeb; font-size:13px;">
                    Evaluating Neighbor Consensus ({agree_cnt}/{tot_cnt} Direct Neighbors Agree — Majority Threshold: {maj_thresh}/{tot_cnt})
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="alert-banner-safe">
                    Normal System State (No Confirmed Hazard)
                </div>
                """,
                unsafe_allow_html=True,
            )

st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# BOTTOM SECTION — 4 CARDS (ENERGY | STATS | PACKET FLOW | LOG)
# -----------------------------------------------------------------------------
bcol1, bcol2, bcol3, bcol4 = st.columns([1.1, 1.0, 1.1, 1.2])

with bcol1:
    st.markdown("<div class='card-hdr'><span>Energy Levels (Battery %)</span></div>", unsafe_allow_html=True)

    batt_names = [n.name for n in world.nodes]
    batt_vals = [int(n.battery) for n in world.nodes]
    colors = [
        "#0284c7" if n.solar_recharging else ("#059669" if n.battery > 50 else ("#d97706" if n.battery > 25 else "#dc2626"))
        for n in world.nodes
    ]

    fig_batt = go.Figure(
        data=[
            go.Bar(
                x=batt_names,
                y=batt_vals,
                marker_color=colors,
                text=[f"{v}%" for v in batt_vals],
                textposition="auto",
            )
        ]
    )
    fig_batt.update_layout(
        height=195,
        margin=dict(l=5, r=5, t=10, b=5),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#334155", size=10.5),
        yaxis=dict(range=[0, 100], visible=False),
        xaxis=dict(tickfont=dict(color="#0f172a", size=10, weight="bold")),
    )
    st.plotly_chart(fig_batt, use_container_width=True, config={"displayModeBar": False})

with bcol2:
    st.markdown("<div class='card-hdr'><span>Network Statistics</span></div>", unsafe_allow_html=True)
    stats = compute_network_stats(world)

    st.markdown(
        f"""
        <div style="font-size:13px; line-height:2.0; padding:2px 0;">
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Active Nodes:</span><b style="color:#0f172a;">{stats['active_nodes']}</b></div>
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Cluster Heads:</span><b style="color:#9333ea;">{stats['cluster_heads']}</b></div>
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Solar Recharging:</span><b style="color:#0284c7;">{stats['solar_recharging']} Nodes</b></div>
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Total Packets:</span><b style="color:#0f172a;">{stats['total_packets']}</b></div>
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Successful Delivery:</span><b style="color:#059669;">{stats['successful_delivery']}</b></div>
            <div style="display:flex; justify-content:space-between;"><span style="color:#64748b;">Average Battery:</span><b style="color:#0284c7;">{stats['avg_battery']}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    from simulation import export_simulation_history_csv, sync_simulation_to_firebase
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🔥 Sync Firebase", use_container_width=True):
            synced = sync_simulation_to_firebase(world, force=True)
            if synced:
                st.toast("Synced to Cloud Firestore!", icon="✅")
            else:
                st.toast("Buffered offline write queue.", icon="ℹ️")

    with btn_col2:
        csv_data = export_simulation_history_csv(world)
        st.download_button(
            label="📥 Export CSV",
            data=csv_data,
            file_name=f"environ_x_telemetry_{world.sim_clock.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


with bcol3:
    st.markdown("<div class='card-hdr'><span>Packet Flow (LoRa Transmission)</span></div>", unsafe_allow_html=True)

    if world.packet_flow_state:
        steps = world.packet_flow_state
        step1 = steps[0] if len(steps) > 0 else {}
        step2 = steps[1] if len(steps) > 1 else {}
        
        flow_path_html = f"""
        <div style="background:#f0f9ff; border:1px solid #bae6fd; border-radius:6px; padding:8px 10px; font-weight:800; font-size:13px; color:#0284c7; text-align:center; margin-bottom:8px;">
            {step1.get('from', 'Node')} <span style="color:#64748b;">({step1.get('from_role', 'Member')})</span> ➔ {step1.get('to', 'CH')} <span style="color:#9333ea;">(Cluster Head)</span> ➔ {step2.get('to', 'GW-01')} <span style="color:#dc2626;">(Gateway)</span>
        </div>
        <div style="font-size:11.5px; color:#334155; line-height:1.6;">
            <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #f1f5f9;">
                <span><b>Step 1:</b> {step1.get('from')} ➔ {step1.get('to')} <span style="color:#64748b;">({step1.get('type', 'Alert')})</span></span>
                <span style="color:#059669; font-weight:bold;">{step1.get('status', 'OK')}</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:3px 0;">
                <span><b>Step 2:</b> {step2.get('from')} ➔ {step2.get('to')} <span style="color:#64748b;">({step2.get('type', 'Aggregate Payload')})</span></span>
                <span style="color:#0284c7; font-weight:bold;">{step2.get('status', 'OK')}</span>
            </div>
        </div>
        """
        st.markdown(flow_path_html, unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:22px 12px; font-size:12.5px; color:#64748b; font-weight:500; text-align:center; margin-top:8px;">
                Idle telemetry. Select a hazard scenario to view LoRa packet routing.
            </div>
            """,
            unsafe_allow_html=True,
        )


with bcol4:
    st.markdown(
        """
        <div class="card-hdr">
            <span>Real-Time Event Log</span>
            <span style="font-size:12px; color:#64748b; font-weight:600;">Live Feed</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    log_html = "<div style='height:185px; overflow-y:auto; font-family:monospace; font-size:11.5px; color:#334155; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px;'>"
    for item in world.event_log[:10]:
        lvl_color = "#dc2626" if item["level"] == "CRITICAL" else ("#d97706" if item["level"] == "WARNING" else "#059669")
        log_html += f"<div style='margin-bottom:4px;'><span style='color:#64748b;'>{item['time']}</span> <span style='color:{lvl_color}; font-weight:bold;'>[{item['type']}]</span> <span style='color:#1e293b;'>{item['detail']}</span></div>"
    log_html += "</div>"

    st.markdown(log_html, unsafe_allow_html=True)

if world.running:
    time.sleep(1.0)
    st.rerun()
