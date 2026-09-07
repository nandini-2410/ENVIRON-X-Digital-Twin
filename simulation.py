"""
simulation.py — Physics, Spatial Hazard Diffusion, 12 Node State with Solar Energy Harvesting for ENVIRON-X.
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

SCENARIOS = [
    "NORMAL",
    "WILDFIRE",
    "FLOOD",
    "GAS LEAK",
    "LANDSLIDE",
    "SENSOR FAILURE",
    "COMMUNICATION FAILURE",
    "LOW BATTERY",
]


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def dist_geo(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot(dlat, dlon)


@dataclass
class Sensors:
    temperature: float = 28.1
    humidity: float = 62.0
    gas: float = 85.0
    smoke: float = 15.0
    pressure: float = 1008.0
    motion: float = 0.12
    water_level: float = 0.3
    flow_rate: float = 0.5
    rainfall: float = 0.0
    soil_moisture: float = 35.0
    tilt: float = 0.2
    vibration: float = 0.1
    solar_irradiance: float = 850.0  # W/m^2 Solar Power


@dataclass
class Node:
    nid: int
    name: str
    zone: str              # "Forest Zone", "River / Floody Zone", "Hilly Slope Zone"
    zone_icon: str         # 🌲, 🌊, ⛰️
    elevation: str         # "318 m"
    sensor_suite: List[str]# Active sensor types
    lat: float
    lon: float
    x: float
    y: float
    role: str = "Cluster Member"
    is_ch: bool = False
    cluster_id: int = 1
    battery: float = 85.0
    initial_battery: float = 100.0
    status: str = "Normal"
    solar_recharging: bool = False
    failed: bool = False
    comm_failed: bool = False
    sensors: Sensors = field(default_factory=Sensors)
    history: Dict[str, List[float]] = field(default_factory=dict)
    edge_ai: Dict[str, Any] = field(default_factory=dict)
    last_seen: int = 0

    def get_formatted_sensors(self) -> Dict[str, str]:
        """Returns single synchronized string dictionary for both map hover card & node info table."""
        s = self.sensors
        return {
            "temp": f"{s.temperature:.1f} °C",
            "humidity": f"{s.humidity:.0f} %",
            "gas": f"{s.gas:.0f} ppm",
            "smoke": f"{s.smoke:.0f} ppm",
            "pressure": f"{s.pressure:.0f} hPa",
            "motion": f"{s.motion:.2f} g",
            "water": f"{s.water_level:.2f} m",
            "flow": f"{s.flow_rate:.2f} m/s",
            "soil": f"{s.soil_moisture:.1f} %",
            "tilt": f"{s.tilt:.2f} °",
            "vibration": f"{s.vibration:.2f} g",
            "solar": f"{s.solar_irradiance:.0f} W/m²",
        }


@dataclass
class WorldSimulation:
    nodes: List[Node] = field(default_factory=list)
    gateway: Dict[str, Any] = field(default_factory=dict)
    sim_clock: datetime = field(default_factory=lambda: datetime(2026, 9, 7, 14, 32, 10))
    round_num: int = 12
    step_count: int = 0
    scenario: str = "NORMAL"
    intensity: float = 0.0
    scenario_start_step: int = 0
    running: bool = True
    speed: int = 1

    selected_node_id: int = 7
    event_log: List[Dict[str, Any]] = field(default_factory=list)
    consensus_state: Dict[str, Any] = field(default_factory=dict)
    packet_flow_state: List[Dict[str, Any]] = field(default_factory=list)
    gateway_status: Dict[str, Any] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(42))

    def get_node(self, nid: int) -> Node:
        for n in self.nodes:
            if n.nid == nid:
                return n
        return self.nodes[0]


def catalog_nodes() -> List[Dict[str, Any]]:
    return [
        # --- DENSE FOREST ZONE (Spacious 2D Spread across Central Ridge Reserve Forest) ---
        {
            "nid": 1, "name": "N01", "zone": "Forest Zone", "zone_icon": "", "elev": "315 m",
            "sensors": ["Temperature", "Humidity", "Smoke/CO2", "Gas (VOC)", "Barometric Pressure"],
            "lat": 28.6340, "lon": 77.1750, "x": 90, "y": 90, "batt": 88.0
        },
        {
            "nid": 2, "name": "N02", "zone": "Forest Zone", "zone_icon": "", "elev": "318 m",
            "sensors": ["Temperature", "Humidity", "Smoke/CO2", "Gas (VOC)", "Barometric Pressure"],
            "lat": 28.6250, "lon": 77.1650, "x": 200, "y": 120, "batt": 75.0
        },
        {
            "nid": 3, "name": "N03", "zone": "Forest Zone", "zone_icon": "", "elev": "325 m",
            "sensors": ["Temperature", "Humidity", "Smoke/CO2", "Gas (VOC)", "Barometric Pressure"],
            "lat": 28.6180, "lon": 77.1880, "x": 320, "y": 80, "batt": 92.0
        },
        {
            "nid": 7, "name": "N07", "zone": "Forest Zone", "zone_icon": "", "elev": "320 m",
            "sensors": ["Temperature", "Humidity", "Smoke/CO2", "Gas (VOC)", "Barometric Pressure"],
            "lat": 28.6040, "lon": 77.1720, "x": 420, "y": 180, "batt": 78.0
        },

        # --- RIVER / FLOODY ZONE (Spacious spread along Yamuna River bank & flow course) ---
        {
            "nid": 5, "name": "N05", "zone": "River / Floody Zone", "zone_icon": "", "elev": "285 m",
            "sensors": ["Water Level", "River Flow Rate", "Rainfall", "Soil Moisture", "Humidity"],
            "lat": 28.6340, "lon": 77.2480, "x": 110, "y": 250, "batt": 85.0
        },
        {
            "nid": 6, "name": "N06", "zone": "River / Floody Zone", "zone_icon": "", "elev": "288 m",
            "sensors": ["Water Level", "River Flow Rate", "Rainfall", "Soil Moisture", "Humidity"],
            "lat": 28.6200, "lon": 77.2540, "x": 240, "y": 270, "batt": 62.0
        },
        {
            "nid": 11, "name": "N11", "zone": "River / Floody Zone", "zone_icon": "", "elev": "290 m",
            "sensors": ["Water Level", "River Flow Rate", "Rainfall", "Soil Moisture", "Humidity"],
            "lat": 28.6080, "lon": 77.2500, "x": 480, "y": 300, "batt": 89.0
        },

        # --- URBAN / INDUSTRIAL GAS LEAK ZONES ---
        {
            "nid": 4, "name": "N04", "zone": "Industrial Gas Zone", "zone_icon": "", "elev": "310 m",
            "sensors": ["Gas (VOC)", "Smoke/CO2", "Temperature", "Humidity", "Pressure"],
            "lat": 28.6350, "lon": 77.2050, "x": 490, "y": 100, "batt": 81.0
        },
        {
            "nid": 8, "name": "N08", "zone": "Industrial Gas Zone", "zone_icon": "", "elev": "312 m",
            "sensors": ["Gas (VOC)", "Smoke/CO2", "Temperature", "Humidity", "Pressure"],
            "lat": 28.6220, "lon": 77.2180, "x": 170, "y": 380, "batt": 91.0
        },

        # --- HILLY / MOUNTAIN SLOPE ZONE ---
        {
            "nid": 9, "name": "N09", "zone": "Hilly Slope Zone", "zone_icon": "", "elev": "465 m",
            "sensors": ["IMU Motion", "3-Axis Tilt", "Ground Vibration", "Soil Moisture", "Pressure"],
            "lat": 28.5950, "lon": 77.1950, "x": 300, "y": 400, "batt": 83.0
        },
        {
            "nid": 10, "name": "N10", "zone": "Hilly Slope Zone", "zone_icon": "", "elev": "425 m",
            "sensors": ["IMU Motion", "3-Axis Tilt", "Ground Vibration", "Soil Moisture", "Pressure"],
            "lat": 28.5980, "lon": 77.2280, "x": 430, "y": 370, "batt": 79.0
        },
        {
            "nid": 12, "name": "N12", "zone": "Hilly Slope Zone", "zone_icon": "", "elev": "450 m",
            "sensors": ["IMU Motion", "3-Axis Tilt", "Ground Vibration", "Soil Moisture", "Pressure"],
            "lat": 28.6160, "lon": 77.2360, "x": 540, "y": 240, "batt": 95.0
        },
    ]


def init_world() -> WorldSimulation:
    nodes = []
    cat = catalog_nodes()
    for spec in cat:
        seed_off = (spec["nid"] * 0.7) - 4.0
        zone = spec["zone"]
        if zone == "River / Floody Zone":
            water = 0.45 + abs(seed_off) * 0.03
            flow = 0.85 + abs(seed_off) * 0.05
            soil = 55.0 + seed_off * 1.5
            temp = 25.5 + seed_off * 0.3
            hum = 72.0 + seed_off * 0.4
            motion = 0.05
            tilt = 0.1
            vib = 0.04
            gas = 65.0
            smoke = 8.0
        elif zone == "Hilly Slope Zone":
            water = 0.15
            flow = 0.10
            soil = 32.0 + seed_off * 1.0
            temp = 24.0 + seed_off * 0.4
            hum = 58.0 - seed_off * 0.5
            motion = 0.18 + abs(seed_off) * 0.02
            tilt = 0.45 + abs(seed_off) * 0.03
            vib = 0.12 + abs(seed_off) * 0.02
            gas = 70.0
            smoke = 10.0
        else: # Forest Zone
            water = 0.25
            flow = 0.20
            soil = 38.0 + seed_off * 1.2
            temp = 28.2 + seed_off * 0.4
            hum = 62.0 - seed_off * 0.6
            motion = 0.08
            tilt = 0.15
            vib = 0.05
            gas = 85.0 + seed_off * 3.0
            smoke = 12.0 + abs(seed_off) * 0.5

        s = Sensors(
            temperature=temp,
            humidity=hum,
            gas=gas,
            smoke=smoke,
            pressure=1008.0 + seed_off * 0.2,
            motion=motion,
            water_level=water,
            flow_rate=flow,
            rainfall=0.0,
            soil_moisture=soil,
            tilt=tilt,
            vibration=vib,
            solar_irradiance=820.0 + (spec["nid"] % 4) * 40.0,
        )
        hist = {
            "temp": [s.temperature],
            "humidity": [s.humidity],
            "gas": [s.gas],
            "smoke": [s.smoke],
            "water": [s.water_level],
            "motion": [s.motion],
        }
        node = Node(
            nid=spec["nid"],
            name=spec["name"],
            zone=spec["zone"],
            zone_icon=spec["zone_icon"],
            elevation=spec["elev"],
            sensor_suite=spec["sensors"],
            lat=spec["lat"],
            lon=spec["lon"],
            x=spec["x"],
            y=spec["y"],
            battery=spec["batt"],
            initial_battery=100.0,
            sensors=s,
            history=hist,
        )
        nodes.append(node)

    gateway = {
        "name": "GW-01",
        "lat": 28.6150,
        "lon": 77.2280,
        "x": 620,
        "y": 220,
        "status": "ONLINE",
        "packets_received": 1420,
        "packets_forwarded": 1335,
        "delivery_pct": 94.0,
        "last_alert": "None",
    }

    world = WorldSimulation(
        nodes=nodes,
        gateway=gateway,
        selected_node_id=7,
        consensus_state={"status": "IDLE", "agree_count": 0, "total": 5, "hazard": "NORMAL"},
        gateway_status={"status": "ONLINE", "alert": None},
    )

    add_log(world, "SYSTEM ONLINE", "ENVIRON-X Network initialized with Solar Energy Harvesting ecosystem.")
    add_log(world, "DEPLOYMENT", "12 Nodes operating on Solar Power + Automatic LEACH Battery Handoff.")
    return world


def add_log(world: WorldSimulation, event_type: str, detail: str, level: str = "INFO") -> None:
    t_str = world.sim_clock.strftime("%H:%M:%S")
    world.event_log.insert(0, {
        "time": t_str,
        "type": event_type,
        "detail": detail,
        "level": level,
    })
    world.event_log = world.event_log[:50]


def step_sensor_value(current: float, target_base: float, noise_scale: float, rng: random.Random) -> float:
    drift = (target_base - current) * 0.10
    noise = rng.uniform(-noise_scale, noise_scale)
    return current + drift + noise


def get_epicenter(scenario: str) -> Tuple[float, float]:
    epicenters = {
        "WILDFIRE": (28.6200, 77.2120),    # Node 07 (Forest)
        "FLOOD": (28.6120, 77.1960),       # Node 05 (River)
        "GAS LEAK": (28.6260, 77.2070),    # Node 03 (Forest/Pipe)
        "LANDSLIDE": (28.6040, 77.2000),   # Node 08 (Hilly Slope)
    }
    return epicenters.get(scenario, (28.6150, 77.2050))


def update_sensors_step(world: WorldSimulation) -> None:
    rng = world.rng
    world.step_count += 1
    world.sim_clock += timedelta(seconds=1)

    if world.scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        world.intensity = min(1.0, world.intensity + 0.08)
    else:
        world.intensity = max(0.0, world.intensity - 0.1)

    epic_lat, epic_lon = get_epicenter(world.scenario)

    for n in world.nodes:
        if n.failed and world.scenario == "SENSOR FAILURE" and n.nid == 7:
            continue

        s = n.sensors
        d_epic = dist_geo(n.lat, n.lon, epic_lat, epic_lon)
        # Localized Gaussian spatial decay (sigma = 0.70 km) so distant nodes stay Normal (Green)
        spatial_weight = math.exp(-((d_epic / 0.70) ** 2)) * world.intensity

        # Zone-specific baselines
        if n.zone == "River / Floody Zone":
            target_temp = 25.5 + (n.nid % 3) * 0.4
            target_hum = 72.0 + (n.nid % 3) * 0.8
            target_water = 0.45 + (n.nid % 2) * 0.05
            target_flow = 0.85 + (n.nid % 2) * 0.05
            target_gas = 65.0
            target_smoke = 8.0
            target_motion = 0.05
            target_tilt = 0.1
            target_vib = 0.04
        elif n.zone == "Hilly Slope Zone":
            target_temp = 24.0 + (n.nid % 3) * 0.5
            target_hum = 58.0 - (n.nid % 3) * 0.5
            target_water = 0.15
            target_flow = 0.10
            target_gas = 70.0
            target_smoke = 10.0
            target_motion = 0.18 + (n.nid % 2) * 0.03
            target_tilt = 0.45 + (n.nid % 2) * 0.04
            target_vib = 0.12 + (n.nid % 2) * 0.03
        else: # Forest Zone
            target_temp = 28.2 + (n.nid % 3) * 0.5
            target_hum = 62.0 - (n.nid % 4) * 1.0
            target_gas = 85.0 + (n.nid % 5) * 4.0
            target_smoke = 12.0 + (n.nid % 2) * 2.0
            target_water = 0.25
            target_flow = 0.20
            target_motion = 0.08
            target_tilt = 0.15
            target_vib = 0.05

        # Scenario Impacts
        if world.scenario == "WILDFIRE":
            target_temp += 26.0 * spatial_weight
            target_smoke += 360.0 * spatial_weight
            target_gas += 290.0 * spatial_weight
            target_hum -= 42.0 * spatial_weight
        elif world.scenario == "FLOOD":
            target_water += 3.8 * spatial_weight
            target_flow += 4.5 * spatial_weight
            target_hum += 25.0 * spatial_weight
            target_motion += 0.8 * spatial_weight
        elif world.scenario == "GAS LEAK":
            target_gas += 430.0 * spatial_weight
            target_smoke += 65.0 * spatial_weight
        elif world.scenario == "LANDSLIDE":
            target_motion += 4.2 * spatial_weight
            target_tilt += 9.2 * spatial_weight
            target_vib += 4.8 * spatial_weight
            target_water += 0.9 * spatial_weight

        # Solar Irradiance fluctuation
        s.solar_irradiance = clamp(s.solar_irradiance + rng.uniform(-15.0, 15.0), 600.0, 1100.0)

        # Real-time sensor walk
        s.temperature = clamp(step_sensor_value(s.temperature, target_temp, 0.22, rng), 15.0, 60.0)
        s.humidity = clamp(step_sensor_value(s.humidity, target_hum, 0.8, rng), 10.0, 99.0)
        s.gas = clamp(step_sensor_value(s.gas, target_gas, 3.0, rng), 20.0, 600.0)
        s.smoke = clamp(step_sensor_value(s.smoke, target_smoke, 1.5, rng), 0.0, 500.0)
        s.water_level = clamp(step_sensor_value(s.water_level, target_water, 0.04, rng), 0.0, 5.0)
        s.flow_rate = clamp(step_sensor_value(s.flow_rate, target_flow, 0.05, rng), 0.0, 8.0)
        s.motion = clamp(step_sensor_value(s.motion, target_motion, 0.04, rng), 0.0, 6.0)
        s.tilt = clamp(step_sensor_value(s.tilt, target_tilt, 0.05, rng), 0.0, 15.0)
        s.vibration = clamp(step_sensor_value(s.vibration, target_vib, 0.04, rng), 0.0, 10.0)

        # Update history
        n.history["temp"] = (n.history.get("temp", []) + [s.temperature])[-30:]
        n.history["humidity"] = (n.history.get("humidity", []) + [s.humidity])[-30:]
        n.history["gas"] = (n.history.get("gas", []) + [s.gas])[-30:]
        n.history["smoke"] = (n.history.get("smoke", []) + [s.smoke])[-30:]
        n.history["water"] = (n.history.get("water", []) + [s.water_level])[-30:]
        n.history["motion"] = (n.history.get("motion", []) + [s.motion])[-30:]
