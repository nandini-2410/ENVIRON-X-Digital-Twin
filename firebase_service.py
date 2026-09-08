

import os
import json
import logging
import threading
from typing import Dict, List, Any, Optional
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("firebase_service")

# Global Firebase initialization state
_db = None
_initialized = False
_last_error: Optional[str] = None
_offline_queue: List[Dict[str, Any]] = []
_queue_lock = threading.Lock()


def init_firebase() -> bool:
    """
    Initialize Firebase Admin SDK using secrets, environment variable, or local file.
    Returns True if successfully connected, False otherwise.
    """
    global _db, _initialized, _last_error

    if _initialized and _db is not None:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:
        _last_error = f"firebase-admin library missing: {e}"
        logger.warning(_last_error)
        return False

    # Check if already initialized in firebase_admin app registry
    if firebase_admin._apps:
        try:
            _db = firestore.client()
            _initialized = True
            _last_error = None
            return True
        except Exception as e:
            _last_error = f"Error retrieving existing Firestore client: {e}"
            logger.error(_last_error)

    cred = None

    # Priority 1: Streamlit secrets
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "firebase" in st.secrets:
            secrets_dict = dict(st.secrets["firebase"])
            # Format private_key if needed
            if "private_key" in secrets_dict:
                secrets_dict["private_key"] = secrets_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(secrets_dict)
            logger.info("Firebase loaded from st.secrets['firebase']")
    except Exception as e:
        logger.debug(f"Streamlit secrets check omitted or failed: {e}")

    # Priority 2: Environment variable with JSON content
    if not cred and os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
        try:
            env_json = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
            if "private_key" in env_json:
                env_json["private_key"] = env_json["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(env_json)
            logger.info("Firebase loaded from FIREBASE_SERVICE_ACCOUNT environment variable")
        except Exception as e:
            logger.warning(f"Failed to parse FIREBASE_SERVICE_ACCOUNT env var: {e}")

    # Priority 3: Environment variable path
    if not cred and os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH"):
        path = os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"]
        if os.path.exists(path):
            try:
                cred = credentials.Certificate(path)
                logger.info(f"Firebase loaded from FIREBASE_SERVICE_ACCOUNT_PATH: {path}")
            except Exception as e:
                logger.warning(f"Failed to load service account from path {path}: {e}")

    # Priority 4: Local service account file
    if not cred:
        local_path = "firebase_service_account.json"
        if os.path.exists(local_path):
            try:
                cred = credentials.Certificate(local_path)
                logger.info(f"Firebase loaded from local file: {local_path}")
            except Exception as e:
                _last_error = f"Failed to load local credential file: {e}"
                logger.warning(_last_error)

    if not cred:
        _last_error = "No valid Firebase credentials found (checked st.secrets, ENV, local file)"
        logger.info(f"Firebase Offline: {_last_error}")
        return False

    try:
        firebase_admin.initialize_app(cred)
        _db = firestore.client()
        _initialized = True
        _last_error = None
        logger.info("Firebase Cloud Firestore successfully connected.")
        return True
    except Exception as e:
        _last_error = f"Firebase Admin SDK initialization failed: {e}"
        logger.error(_last_error)
        return False


def is_connected() -> bool:
    """Return whether Firebase is active and connected."""
    global _initialized, _db
    if not _initialized or _db is None:
        return init_firebase()
    return True


def get_firebase_status() -> Dict[str, Any]:
    """Return status summary of Firebase connection and pending offline queue."""
    connected = is_connected()
    with _queue_lock:
        queue_count = len(_offline_queue)
    return {
        "connected": connected,
        "pending_queue_count": queue_count,
        "last_error": _last_error if not connected else None,
        "mode": "Online" if connected else "Offline (Buffered)"
    }


def _queue_or_write(collection_name: str, doc_data: Dict[str, Any], doc_id: Optional[str] = None) -> bool:
    """Internal helper to write to Firestore or buffer in queue if offline."""
    doc_data_copy = dict(doc_data)
    if "created_at" not in doc_data_copy:
        doc_data_copy["created_at"] = datetime.utcnow().isoformat()

    if is_connected() and _db is not None:
        try:
            col_ref = _db.collection(collection_name)
            if doc_id:
                col_ref.document(str(doc_id)).set(doc_data_copy, merge=True)
            else:
                col_ref.add(doc_data_copy)
            return True
        except Exception as e:
            logger.warning(f"Firestore write error on {collection_name}: {e}. Buffering offline.")

    # Offline buffer
    with _queue_lock:
        _offline_queue.append({
            "collection": collection_name,
            "data": doc_data_copy,
            "doc_id": doc_id
        })
        # Limit buffer to max 1000 items to prevent RAM bloat
        if len(_offline_queue) > 1000:
            _offline_queue.pop(0)
    return False


def flush_offline_queue() -> int:
    """Flush and send buffered offline messages to Firestore if connection is restored."""
    if not is_connected() or _db is None:
        return 0

    with _queue_lock:
        if not _offline_queue:
            return 0
        items_to_flush = list(_offline_queue)
        _offline_queue.clear()

    flushed_count = 0
    remaining = []

    for item in items_to_flush:
        try:
            col_ref = _db.collection(item["collection"])
            if item["doc_id"]:
                col_ref.document(str(item["doc_id"])).set(item["data"], merge=True)
            else:
                col_ref.add(item["data"])
            flushed_count += 1
        except Exception as e:
            logger.warning(f"Failed to flush item to {item['collection']}: {e}")
            remaining.append(item)

    if remaining:
        with _queue_lock:
            _offline_queue.extend(remaining)

    return flushed_count


# --- Collection Specific APIs ---

def save_node_state(nodes: List[Dict[str, Any]]) -> bool:
    """
    Write or update list of node states in 'nodes' collection.
    Each item in nodes list should be a dict representing a node state.
    """
    success = True
    for node in nodes:
        node_id = node.get("id")
        res = _queue_or_write("nodes", node, doc_id=f"node_{node_id}" if node_id is not None else None)
        if not res:
            success = False
    return success


def save_sensor_reading(readings: List[Dict[str, Any]]) -> bool:
    """
    Write batch of node sensor telemetry readings to 'sensor_readings' collection.
    """
    success = True
    for reading in readings:
        res = _queue_or_write("sensor_readings", reading)
        if not res:
            success = False
    return success


def save_event(event_data: Dict[str, Any]) -> bool:
    """
    Write a system event / alert to 'events' collection.
    """
    return _queue_or_write("events", event_data)


def save_packet(packet_data: Dict[str, Any]) -> bool:
    """
    Write packet transmission record to 'packets' collection.
    """
    return _queue_or_write("packets", packet_data)


def save_leach_round(round_data: Dict[str, Any]) -> bool:
    """
    Write LEACH cluster rotation round info to 'leach_rounds' collection.
    """
    return _queue_or_write("leach_rounds", round_data)


def save_consensus(consensus_data: Dict[str, Any]) -> bool:
    """
    Write neighbor/cluster consensus verification result to 'consensus' collection.
    """
    return _queue_or_write("consensus", consensus_data)


def get_historical_sensor_readings(node_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Query historical sensor readings from Firestore collection 'sensor_readings'.
    """
    if not is_connected() or _db is None:
        return []

    try:
        col_ref = _db.collection("sensor_readings")
        if node_id is not None:
            query = col_ref.where("node_id", "==", node_id).limit(limit)
        else:
            query = col_ref.limit(limit)

        docs = query.stream()
        results = []
        for doc in docs:
            d = doc.to_dict()
            d["_doc_id"] = doc.id
            results.append(d)
        return results
    except Exception as e:
        logger.error(f"Error fetching historical sensor readings: {e}")
        return []
