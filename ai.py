"""
ai.py — Edge Threshold Layer, Zone-Aware TinyML Hazard Classifier, and Multi-Node Consensus Engine for 12 ENVIRON-X Nodes.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List
from simulation import WorldSimulation, Node, add_log
from network import find_packet_route, get_node_neighbors


def softmax(logits: Dict[str, float]) -> Dict[str, float]:
    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def evaluate_edge_ai(node: Node, scenario: str = "NORMAL") -> Dict[str, Any]:
    """Performs zone-aware local edge processing: Threshold Check -> TinyML Softmax Inference."""
    s = node.sensors

    target_zones = {
        "WILDFIRE": "Forest Zone",
        "FLOOD": "River / Floody Zone",
        "GAS LEAK": "Industrial Gas Zone",
        "LANDSLIDE": "Hilly Slope Zone",
    }
    is_target_zone = (target_zones.get(scenario) == node.zone)

    # Zone-specific Threshold Layer checks
    if node.zone == "River / Floody Zone":
        thresholds = {
            "Water Level": (s.water_level > 1.4, f"{s.water_level:.2f} m > 1.40 m"),
            "River Flow Rate": (s.flow_rate > 2.5, f"{s.flow_rate:.2f} m/s > 2.50 m/s"),
            "Soil Moisture": (s.soil_moisture > 75.0, f"{s.soil_moisture:.1f} % > 75.0 %"),
            "Humidity": (s.humidity > 85.0, f"{s.humidity:.0f} % > 85.0 %"),
        }
    elif node.zone == "Hilly Slope Zone":
        thresholds = {
            "3-Axis Tilt": (s.tilt > 2.5, f"{s.tilt:.2f} ° > 2.50 °"),
            "Ground Vibration": (s.vibration > 1.8, f"{s.vibration:.2f} g > 1.80 g"),
            "IMU Motion": (s.motion > 1.2, f"{s.motion:.2f} g > 1.20 g"),
            "Soil Saturation": (s.soil_moisture > 65.0, f"{s.soil_moisture:.1f} % > 65.0 %"),
        }
    elif node.zone == "Industrial Gas Zone":
        thresholds = {
            "Gas (VOC)": (s.gas > 180.0, f"{s.gas:.0f} ppm > 180.0 ppm"),
            "Smoke / CO2": (s.smoke > 35.0, f"{s.smoke:.0f} ppm > 35.0 ppm"),
            "Temperature": (s.temperature > 35.0, f"{s.temperature:.1f} °C > 35.0 °C"),
            "Humidity": (s.humidity < 38.0, f"{s.humidity:.0f} % < 38.0 %"),
        }
    else:  # Forest Zone
        thresholds = {
            "Temperature": (s.temperature > 35.0, f"{s.temperature:.1f} °C > 35.0 °C"),
            "Humidity": (s.humidity < 38.0, f"{s.humidity:.0f} % < 38.0 %"),
            "Smoke / CO2": (s.smoke > 35.0, f"{s.smoke:.0f} ppm > 35.0 ppm"),
            "Gas (VOC)": (s.gas > 180.0, f"{s.gas:.0f} ppm > 180.0 ppm"),
        }

    threshold_passed = {k: v[0] for k, v in thresholds.items()}
    hits = sum(1 for v in threshold_passed.values() if v)

    # Logits calculation: Active hazard scenario boosts confidence (99% for epicenter, 92%-96% for network nodes)
    epicenter_nids = {"WILDFIRE": 7, "FLOOD": 11, "GAS LEAK": 8, "LANDSLIDE": 9}
    is_epicenter = (epicenter_nids.get(scenario) == node.nid)
    hazard_boost = 12.0 if is_epicenter else 8.0

    if scenario in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        logits = {
            "Normal": 0.2,
            "Wildfire": (hazard_boost if scenario == "WILDFIRE" else 0.1) + 0.18 * max(0, s.temperature - 30),
            "Flood": (hazard_boost if scenario == "FLOOD" else 0.1) + 2.5 * max(0, s.water_level - 0.4),
            "Gas Leak": (hazard_boost if scenario == "GAS LEAK" else 0.1) + 0.05 * max(0, s.gas - 110),
            "Landslide": (hazard_boost if scenario == "LANDSLIDE" else 0.1) + 1.4 * max(0, s.tilt - 0.3),
        }
        predicted_hazard = scenario.title()
    else:
        logits = {
            "Normal": 4.0,
            "Wildfire": 0.18 * max(0, s.temperature - 30) + 0.12 * max(0, 55 - s.humidity) + 0.08 * s.smoke,
            "Flood": 2.5 * max(0, s.water_level - 0.4) + 1.6 * max(0, s.flow_rate - 0.5),
            "Gas Leak": 0.05 * max(0, s.gas - 110) + 0.04 * s.smoke,
            "Landslide": 1.4 * max(0, s.tilt - 0.3) + 1.2 * max(0, s.vibration - 0.1),
        }
        predicted_hazard = max(logits, key=logits.get)

    probs = softmax(logits)
    confidence = probs.get(predicted_hazard, 0.95)

    if predicted_hazard == "Normal":
        status = "Normal"
    elif confidence >= 0.65:
        status = "CRITICAL HAZARD"
    else:
        status = "Anomaly Detected"

    node.status = status
    res = {
        "thresholds": thresholds,
        "hits": hits,
        "probs": probs,
        "hazard": predicted_hazard,
        "confidence": confidence,
        "status": status,
    }
    node.edge_ai = res
    return res


def run_multi_node_consensus(world: WorldSimulation) -> Dict[str, Any]:
    active_nodes = [n for n in world.nodes if not n.failed]
    for n in active_nodes:
        evaluate_edge_ai(n, world.scenario)

    alert_nodes = [n for n in active_nodes if n.edge_ai.get("hazard") != "Normal"]

    if not alert_nodes or world.scenario not in ["WILDFIRE", "FLOOD", "GAS LEAK", "LANDSLIDE"]:
        state = {
            "status": "IDLE",
            "hazard": "NORMAL",
            "agree_count": 0,
            "total_nodes": 5,
            "confidence": 0.0,
            "affected_nodes": [],
            "confirmed": False,
        }
        world.consensus_state = state
        world.gateway_status["alert"] = None
        world.packet_flow_state = []
        return state

    # Permanently fixed epicenter node per scenario to prevent role jumping/flickering
    fixed_seed_nids = {
        "WILDFIRE": 7,    # Permanently Node N07 in Forest Zone
        "FLOOD": 11,      # Permanently Node N11 in River / Floody Zone
        "GAS LEAK": 8,    # Permanently Node N08 in Industrial Gas Zone
        "LANDSLIDE": 9,   # Permanently Node N09 in Hilly Slope Zone
    }
    epic_nid = fixed_seed_nids.get(world.scenario, 7)
    seed_node = world.get_node(epic_nid)
    detected_hazard = world.scenario.title()

    # Get direct mesh neighbors of the epicenter seed node, sorted by proximity to seed_node
    direct_neighbors = get_node_neighbors(world, seed_node.nid)
    direct_neighbors.sort(key=lambda n: math.hypot(n.lat - seed_node.lat, n.lon - seed_node.lon))

    # Auto-detect scenario change and reset scenario timer and logging trackers
    if getattr(world, "_current_scenario_tracker", None) != world.scenario:
        world._current_scenario_tracker = world.scenario
        world.scenario_start_step = world.step_count
        world._last_logged_confirm_cnt = -1

    # Staggered confirmation schedule with deliberate time gaps (2s, 4s, 6s, 8s, 10s)
    # 1st neighbor at t=2s, 2nd at t=4s (2s gap), 3rd at t=6s (2s gap), 4th at t=8s (2s gap), 5th at t=10s (2s gap)
    thresholds = [2, 4, 6, 8, 10]
    elapsed = max(0, world.step_count - getattr(world, "scenario_start_step", 0))
    active_confirm_count = 0
    for t in thresholds:
        if elapsed >= t:
            active_confirm_count += 1
        else:
            break
    active_confirm_count = min(len(direct_neighbors), active_confirm_count)

    confirming_neighbors = direct_neighbors[:active_confirm_count]
    pending_neighbors = [n for n in direct_neighbors if n not in confirming_neighbors]

    agree_count = len(confirming_neighbors)
    total_neighbors = len(direct_neighbors)

    # Dynamic majority threshold: ceil(total_neighbors / 2) -> 2/3 for Flood, 3/5 for Wildfire
    majority_threshold = math.ceil(total_neighbors / 2.0)
    confirmed = (agree_count >= majority_threshold)

    ordinals = ["1st", "2nd", "3rd", "4th", "5th"]

    # Enforce strict single red epicenter status & neighbor statuses
    for n in world.nodes:
        if getattr(n, "is_hardware", False):
            continue
        elif n.failed:
            n.status = "Offline (Fault)"
        elif n.nid == seed_node.nid:
            n.status = f"CRITICAL HAZARD ({world.scenario})"
        elif n in confirming_neighbors:
            n.status = "Confirming Neighbor"
        elif n in pending_neighbors:
            n.status = "Awaiting Consensus"
        else:
            n.status = "Normal"

    neighbor_sequence = []
    for i, n in enumerate(direct_neighbors):
        ord_lbl = ordinals[i] if i < len(ordinals) else f"{i+1}th"
        is_conf = i < active_confirm_count
        neighbor_sequence.append({
            "order": ord_lbl,
            "node": n.name,
            "confirmed": is_conf,
            "label": f"{ord_lbl} Neighbor ({n.name})",
        })

    # Log sequential neighbor confirmation step-by-step as each neighbor confirms
    if agree_count > 0 and agree_count > getattr(world, "_last_logged_confirm_cnt", -1):
        world._last_logged_confirm_cnt = agree_count
        world._last_logged_scen = world.scenario
        latest_neighbor = confirming_neighbors[-1]
        latest_ord = ordinals[agree_count - 1] if (agree_count - 1) < len(ordinals) else f"{agree_count}th"
        add_log(
            world,
            "NEIGHBOR CONFIRMATION",
            f"{latest_ord} Neighbor ({latest_neighbor.name}) confirmed {detected_hazard} at {seed_node.name} ({agree_count}/{total_neighbors}).",
            level="CRITICAL" if confirmed else "WARNING",
        )

    if agree_count == 0:
        status_text = f"BROADCASTING HAZARD SIGNAL ({seed_node.name})"
    elif confirmed:
        latest_ord = ordinals[agree_count - 1] if (agree_count - 1) < len(ordinals) else f"{agree_count}th"
        status_text = f"{latest_ord.upper()} NEIGHBOR CONFIRMED — {detected_hazard.upper()} CONSENSUS ACHIEVED ({agree_count}/{total_neighbors})"
    else:
        latest_ord = ordinals[agree_count - 1] if (agree_count - 1) < len(ordinals) else f"{agree_count}th"
        status_text = f"{latest_ord.upper()} NEIGHBOR CONFIRMED — EVALUATING CONSENSUS ({agree_count}/{total_neighbors})"

    if confirmed:
        route = find_packet_route(world, seed_node.nid)
        # Build explicit packet transmission steps: Member -> Cluster Head -> Gateway
        ch_node = world.get_node(seed_node.cluster_id)
        world.packet_flow_state = [
            {
                "step": 1,
                "from": seed_node.name,
                "from_role": "Cluster Head" if seed_node.is_ch else "Member Node",
                "to": ch_node.name,
                "to_role": "Cluster Head",
                "type": "Telemetry Alert",
                "size": "64 Bytes",
                "status": "Transmitted to CH",
            },
            {
                "step": 2,
                "from": ch_node.name,
                "from_role": "Cluster Head",
                "to": "GW-01",
                "to_role": "Gateway",
                "type": "Aggregated Emergency Payload",
                "size": "256 Bytes",
                "status": "Delivered to Gateway",
            }
        ]

        if world.gateway_status.get("alert") != detected_hazard:
            add_log(
                world,
                "NEIGHBOR CONSENSUS",
                f"Majority consensus achieved ({agree_count}/{total_neighbors} direct neighbors agree) — {detected_hazard} confirmed at {seed_node.name}!",
                level="CRITICAL",
            )
            add_log(
                world,
                "PACKET TRANSMISSION",
                f"LoRa alert packet routed: {' -> '.join(route)} (Member ➔ Cluster Head ➔ Gateway)",
                level="WARNING",
            )
            world.gateway_status["alert"] = {
                "hazard": detected_hazard,
                "node": seed_node.name,
                "zone": seed_node.zone,
                "confidence": seed_node.edge_ai.get("confidence", 0.92),
                "consensus": f"{agree_count}/{total_neighbors} Neighbors",
            }
    else:
        world.packet_flow_state = []

    state = {
        "status": status_text,
        "hazard": detected_hazard,
        "agree_count": agree_count,
        "total_nodes": total_neighbors,
        "confidence": seed_node.edge_ai.get("confidence", 0.85),
        "affected_nodes": [n.name for n in confirming_neighbors],
        "pending_nodes": [n.name for n in pending_neighbors],
        "neighbor_sequence": neighbor_sequence,
        "confirmed": confirmed,
        "seed_node": seed_node.name,
        "seed_nid": seed_node.nid,
    }
    world.consensus_state = state

    # Sync consensus & event to Firebase
    try:
        import firebase_service
        firebase_service.save_consensus({
            "seed_node": seed_node.name,
            "seed_nid": seed_node.nid,
            "hazard": detected_hazard,
            "agree_count": agree_count,
            "total_nodes": total_neighbors,
            "confirmed": confirmed,
            "status": status_text,
            "sim_minute": world.sim_clock.minute,
            "timestamp": world.sim_clock.strftime("%Y-%m-%d %H:%M:%S")
        })

        if confirmed:
            firebase_service.save_event({
                "type": f"{detected_hazard.upper()}_ALERT",
                "hazard": detected_hazard,
                "origin_node": seed_node.name,
                "origin_nid": seed_node.nid,
                "confidence": round(seed_node.edge_ai.get("confidence", 0.92) * 100, 1),
                "sim_minute": world.sim_clock.minute,
                "timestamp": world.sim_clock.strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception:
        pass

    return state




