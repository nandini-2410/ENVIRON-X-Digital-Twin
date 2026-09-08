"""
network.py — LEACH-style Clustering, Solar Energy Harvesting, and Critical Battery CH Handoff Engine for ENVIRON-X.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Tuple
from simulation import WorldSimulation, Node, add_log, clamp

INTER_NODE_LINKS = [
    (1, 2), (2, 3), (3, 7), (7, 1),
    (1, 4), (2, 4), (3, 8), (7, 8),
    (4, 8), (4, 5), (8, 12), (12, 6),
    (5, 6), (6, 11),
    (7, 9), (8, 9), (9, 10), (10, 12), (10, 11)
]

# Critical Battery Threshold for CH Handoff
CRITICAL_CH_BATTERY_THRESHOLD = 25.0


def get_inter_node_links() -> List[Tuple[int, int]]:
    return INTER_NODE_LINKS


def get_node_neighbors(world: WorldSimulation, nid: int) -> List[Node]:
    """Returns direct mesh neighbor nodes connected via INTER_NODE_LINKS to the target node."""
    neighbor_ids = set()
    for u, v in INTER_NODE_LINKS:
        if u == nid:
            neighbor_ids.add(v)
        elif v == nid:
            neighbor_ids.add(u)
    return [world.get_node(n_id) for n_id in neighbor_ids if not world.get_node(n_id).failed]


def leach_elect_clusters(world: WorldSimulation, target_chs: int = 4) -> List[int]:
    """LEACH-style energy-aware Cluster Head election prioritizing high-battery nodes."""
    world.round_num += 1
    candidates = [n for n in world.nodes if not n.failed and n.battery > 28.0]

    if not candidates:
        candidates = [n for n in world.nodes if not n.failed]

    if not candidates:
        return []

    scored = []
    for n in candidates:
        n.is_ch = False
        battery_weight = (n.battery / 100.0) ** 2.0
        score = battery_weight * world.rng.random()
        scored.append((score, n))

    scored.sort(key=lambda item: item[0], reverse=True)
    ch_nodes = [n for _, n in scored[:min(target_chs, len(scored))]]

    ch_ids = [n.nid for n in ch_nodes]
    for n in ch_nodes:
        n.is_ch = True
        n.role = "Cluster Head"
        n.cluster_id = n.nid
        n.solar_recharging = False

    for n in world.nodes:
        if not n.failed and not n.is_ch:
            n.role = "Cluster Member"
            nearest_ch = min(
                ch_nodes,
                key=lambda ch: math.hypot(n.lat - ch.lat, n.lon - ch.lon)
            )
            n.cluster_id = nearest_ch.nid

    ch_names = ", ".join([f"CH-{ch_id:02d}" for ch_id in ch_ids])
    add_log(world, "LEACH ROTATION", f"Round {world.round_num}: New Cluster Heads elected [{ch_names}]. Only CHs transmit to Gateway.")

    try:
        import firebase_service
        firebase_service.save_leach_round({
            "round": world.round_num,
            "cluster_heads": ch_ids,
            "sim_minute": world.sim_clock.minute,
            "timestamp": world.sim_clock.strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception:
        pass

    return ch_ids



def consume_energy_step(world: WorldSimulation) -> None:
    """Simulates Solar Energy Harvesting & Critical Battery CH Handoff Engine."""
    trigger_handoff = False
    low_ch_name = ""

    for n in world.nodes:
        if getattr(n, "is_hardware", False) or n.failed:
            continue

        if world.scenario == "LOW BATTERY":
            n.battery = max(12.0, n.battery - 1.5)
            continue

        if n.is_ch:
            # Cluster Head transmits long-range to Gateway GW-01 -> Discharges battery
            drain = world.rng.uniform(0.35, 0.65)
            n.battery = max(10.0, n.battery - drain)

            # Check Critical Battery Handoff Threshold (25%)
            if n.battery <= CRITICAL_CH_BATTERY_THRESHOLD:
                trigger_handoff = True
                low_ch_name = n.name
                n.is_ch = False
                n.solar_recharging = True
                n.status = "Solar Recharging"
        else:
            # Member Node / Solar Harvesting Node
            sensing_drain = 0.05
            solar_gain = world.rng.uniform(0.30, 0.70) if n.battery < 95.0 else 0.0

            n.battery = clamp(n.battery - sensing_drain + solar_gain, 12.0, 100.0)

            if n.battery >= 85.0 and n.solar_recharging:
                n.solar_recharging = False
                n.status = "Normal"
                add_log(world, "SOLAR HARVEST", f"{n.name} solar recharging complete ({int(n.battery)}%). Fully operational ☀️", level="INFO")

    if trigger_handoff:
        add_log(
            world,
            "CRITICAL CH HANDOFF",
            f"{low_ch_name} reached battery threshold ({int(CRITICAL_CH_BATTERY_THRESHOLD)}%). Handing off CH role & entering Solar Recharging ☀️",
            level="WARNING",
        )
        leach_elect_clusters(world, target_chs=4)


def find_packet_route(world: WorldSimulation, src_nid: int) -> List[str]:
    """Packet Route: Source Node -> Cluster Head -> Gateway GW-01."""
    src = world.get_node(src_nid)
    ch_id = src.cluster_id
    ch_node = world.get_node(ch_id)

    path = [src.name]
    if src.nid != ch_id:
        path.append(ch_node.name)

    path.append("GW-01")

    clean_path = []
    for step in path:
        if not clean_path or clean_path[-1] != step:
            clean_path.append(step)

    try:
        import firebase_service
        firebase_service.save_packet({
            "sender_node": src.nid,
            "ch_node": ch_id,
            "route_path": clean_path,
            "sim_minute": world.sim_clock.minute,
            "timestamp": world.sim_clock.strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception:
        pass

    return clean_path



def compute_network_stats(world: WorldSimulation) -> Dict[str, Any]:
    active_count = len([n for n in world.nodes if not n.failed])
    ch_count = len([n for n in world.nodes if n.is_ch and not n.failed])
    recharging_count = len([n for n in world.nodes if n.solar_recharging])
    avg_battery = sum(n.battery for n in world.nodes) / max(1, len(world.nodes))

    total_packets = 1420 + world.step_count * 3
    success_pct = 94.0 if world.scenario != "COMMUNICATION FAILURE" else 85.5
    successful_packets = int(total_packets * (success_pct / 100.0))

    return {
        "active_nodes": f"{active_count}/12",
        "cluster_heads": ch_count,
        "solar_recharging": recharging_count,
        "total_packets": f"{total_packets:,}",
        "successful_delivery": f"{successful_packets:,} ({success_pct:.1f}%)",
        "avg_battery": f"{int(avg_battery)}%",
        "latency": "1.2 s" if world.scenario == "NORMAL" else "2.2 s",
    }
