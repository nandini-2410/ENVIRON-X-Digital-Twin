# 🌿 ENVIRON-X — Environmental Intelligence Network & Digital Twin Simulator

**ENVIRON-X** is a light-engineering interactive WSN (Wireless Sensor Network) digital twin dashboard built using Streamlit, PyDeck, Plotly, and Python.

---

## 🚀 Key Features

1. **Light Engineering Theme & Modern Typography**
   - Professional off-white slate interface (`#f8fafc`), clean white cards, Outfit & Plus Jakarta Sans typography.
   - Fully optimized font hierarchy for maximum legibility.

2. **Realistic Light Green Map Background (CARTO Voyager)**
   - High-resolution environmental map showing lush green land cover, parks, rivers, topographic contours, and bright roads without requiring Mapbox API tokens.

3. **Spatially Accurate 2D Polygon Node Placement**
   - **Forest Protection Cluster (`N01`, `N02`, `N03`, `N07`)**: Positioned in a wide, non-linear 2D polygon across the Central Ridge Reserve Forest.
   - **River / Flood Cluster (`N05`, `N06`, `N11`)**: Positioned along the Yamuna River bank and water flow channel.
   - **Industrial Gas Cluster (`N04`, `N08`)**: Positioned in the central commercial/industrial hub.
   - **Hilly Slope Cluster (`N09`, `N10`, `N12`)**: Positioned along southern elevated slope terrain.

4. **Zone-Aware Physical Scenario Alignment**
   - **Wildfire Hazard**: Fixed epicenter at **`N07` (Forest Zone)**. Non-forest nodes like `N08` remain normal.
   - **Flood Hazard**: Fixed epicenter at **`N11` (River / Floody Zone)**.
   - **Gas Leak Hazard**: Fixed epicenter at **`N08` (Industrial Gas Zone)**.
   - **Landslide Hazard**: Fixed epicenter at **`N09` (Hilly Slope Zone)**.

5. **Sequential 1-by-1 Neighbor Consensus**
   - Epicenter node sends yellow verification signals to direct mesh neighbors.
   - Neighbors confirm consensus sequentially with **2-second timing gaps** (1st neighbor at 2s → 2nd neighbor at 4s → 3rd neighbor at 6s).
   - Neighbors turn **YELLOW** upon confirmation.

6. **Corrected Red Alert Packet Routing**
   - Once consensus is confirmed, high-priority **RED ALERT PACKET DOTS** (`radius=70`) stream directly from:
     **Red Epicenter Node ➔ Cluster Head (CH) ➔ Gateway (GW-01)**.

---

## 🛠️ Project Structure

- `app.py`: Main Streamlit interactive user interface & PyDeck map renderer.
- `firebase_service.py`: Firebase Cloud Firestore SDK wrapper, offline queue buffer, and Firestore reader/writer functions.
- `ai.py`: Edge threshold checks, zone-aware TinyML hazard classifier, and multi-node consensus engine.
- `simulation.py`: Spatial node catalog, environmental sensor physics, solar energy harvesting, and minute-deduplicated Firebase persistence.
- `network.py`: LEACH clustering engine, inter-node mesh topology, critical battery handoff, and packet logging.
- `test_firebase.py`: Standalone verification test for Firebase connectivity and CRUD operations.
- `requirements.txt`: Python package dependencies.

---

## ⚡ Firebase Cloud Firestore Integration

ENVIRON-X integrates with **Google Cloud Firestore** to persist WSN telemetry, node topology, LEACH cluster rotations, packets, events, and neighbor consensus records.

### 🔑 Credential Configuration Methods
`firebase_service.py` automatically resolves credentials in the following order:

1. **Streamlit Secrets (`.streamlit/secrets.toml`)**:
   ```toml
   [firebase]
   type = "service_account"
   project_id = "environ-x"
   private_key_id = "YOUR_KEY_ID"
   private_key = "-----BEGIN PRIVATE KEY-----\n..."
   client_email = "firebase-adminsdk-xxx@environ-x.iam.gserviceaccount.com"
   ```

2. **Environment Variable (`FIREBASE_SERVICE_ACCOUNT`)**:
   Set `FIREBASE_SERVICE_ACCOUNT` to your JSON string content or `FIREBASE_SERVICE_ACCOUNT_PATH` to the file path.

3. **Local File (`firebase_service_account.json`)**:
   Place your downloaded service account key JSON file in the project root directory (`c:\Users\Nandini\Documents\SIH\ENVIRON-X_Project\firebase_service_account.json`).

> **Note**: If credentials are not provided or network is offline, the application runs normally without crashing and buffers all pending writes in an offline retry queue.

### 🗄️ Firestore Collections Schema
1. **`nodes`**: Active node status, battery level, role, latitude/longitude, zone assignment.
2. **`sensor_readings`**: Minute-deduplicated environmental telemetry (temperature, humidity, gas, smoke, water level, motion, tilt, vibration, solar irradiance).
3. **`events`**: System logs, hazard detection alerts, and fault injection events.
4. **`packets`**: Transmission route traces (Sender ➔ Cluster Head ➔ Gateway).
5. **`leach_rounds`**: Energy-aware LEACH cluster head election history.
6. **`consensus`**: Multi-node neighbor confirmation states and confidence metrics.

---

## 💻 How to Run & Test

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Firebase Integration Test**:
   ```bash
   python test_firebase.py
   ```

3. **Launch Dashboard**:
   ```bash
   streamlit run app.py
   ```

4. Open your browser at `http://localhost:8501`.

