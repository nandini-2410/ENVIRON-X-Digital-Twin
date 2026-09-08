
import sys
import time
from datetime import datetime
import firebase_service

def main():
    print("==================================================")
    print("   ENVIRON-X Firebase Firestore Integration Test   ")
    print("==================================================")
    
    print("\n1. Initializing Firebase connection...")
    connected = firebase_service.init_firebase()
    status = firebase_service.get_firebase_status()
    
    print(f"   Connection Status : {status['mode']}")
    print(f"   Is Connected      : {status['connected']}")
    if status['last_error']:
        print(f"   Last Error/Info   : {status['last_error']}")
    print(f"   Pending Queue     : {status['pending_queue_count']}")
    
    print("\n2. Testing 'nodes' collection write...")
    test_node = {
        "id": 99,
        "name": "Test Node 99",
        "zone": "Forest Zone",
        "lat": 18.5204,
        "lng": 73.8567,
        "battery": 95.5,
        "status": "NORMAL",
        "timestamp": datetime.utcnow().isoformat()
    }
    node_res = firebase_service.save_node_state([test_node])
    print(f"   Save Node State   : {'[SUCCESS]' if node_res else '[BUFFERED OFFLINE]'}")
    
    print("\n3. Testing 'sensor_readings' collection write...")
    test_reading = {
        "node_id": 99,
        "temperature": 28.5,
        "humidity": 45.0,
        "smoke": 12.0,
        "water_level": 0.5,
        "sim_minute": 1,
        "sim_time": "12:01",
        "hazard_type": "NORMAL",
        "confidence": 0.12,
        "timestamp": datetime.utcnow().isoformat()
    }
    sensor_res = firebase_service.save_sensor_reading([test_reading])
    print(f"   Save Sensor Data  : {'[SUCCESS]' if sensor_res else '[BUFFERED OFFLINE]'}")
    
    print("\n4. Testing 'events' collection write...")
    test_event = {
        "event_id": "EVT_TEST_001",
        "type": "WILDFIRE_ALERT",
        "node_id": 7,
        "confidence": 0.94,
        "severity": "CRITICAL",
        "sim_minute": 1,
        "timestamp": datetime.utcnow().isoformat()
    }
    event_res = firebase_service.save_event(test_event)
    print(f"   Save Event        : {'[SUCCESS]' if event_res else '[BUFFERED OFFLINE]'}")
    
    print("\n5. Testing 'packets' collection write...")
    test_packet = {
        "packet_id": "PKT_001",
        "sender": 7,
        "receiver": 2,
        "signal_type": "YELLOW_WARNING",
        "sim_minute": 1,
        "timestamp": datetime.utcnow().isoformat()
    }
    packet_res = firebase_service.save_packet(test_packet)
    print(f"   Save Packet       : {'[SUCCESS]' if packet_res else '[BUFFERED OFFLINE]'}")

    print("\n6. Testing 'leach_rounds' collection write...")
    test_leach = {
        "round": 1,
        "cluster_heads": [2, 8],
        "energy_consumed_j": 0.45,
        "timestamp": datetime.utcnow().isoformat()
    }
    leach_res = firebase_service.save_leach_round(test_leach)
    print(f"   Save LEACH Round  : {'[SUCCESS]' if leach_res else '[BUFFERED OFFLINE]'}")

    print("\n7. Testing 'consensus' collection write...")
    test_consensus = {
        "origin_node": 7,
        "neighbors_confirming": [2, 5],
        "status": "CONFIRMED",
        "confidence": 0.94,
        "timestamp": datetime.utcnow().isoformat()
    }
    consensus_res = firebase_service.save_consensus(test_consensus)
    print(f"   Save Consensus    : {'[SUCCESS]' if consensus_res else '[BUFFERED OFFLINE]'}")

    if status['connected']:
        print("\n8. Testing historical retrieval from Firestore...")
        readings = firebase_service.get_historical_sensor_readings(node_id=99, limit=5)
        print(f"   Fetched {len(readings)} historical sensor readings for Node 99.")
    else:
        print("\n8. Flushing offline queue test...")
        flushed = firebase_service.flush_offline_queue()
        print(f"   Flushed {flushed} items from offline queue.")

    print("\n==================================================")
    print("   Firebase Service Verification Complete!        ")
    print("==================================================")

if __name__ == "__main__":
    main()
