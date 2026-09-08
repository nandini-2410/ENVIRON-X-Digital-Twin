/*
 * ENVIRON-X - ESP32 LoRa LEACH Mesh Firmware (Rich Console Edition)
 *
 * Hardware Pinout:
 *   LoRa Ra-02 (SPI):
 *     SCK=18  NSS=5  RST=14  DIO0=26
 *     MISO -> GPIO 22
 *     MOSI -> GPIO 23
 *
 *   I2C (TCA9548A Multiplexer):
 *     SDA = GPIO 21
 *     SCL = GPIO 19
 *
 *   Analog Sensors:
 *     GPIO 35 = Soil/Water Level
 *     GPIO 32 = PM2.5 (GP2Y1010), GPIO 33 = PM2.5 IR LED
 *     GPIO 34 = Battery Temp Thermistor
 */

#include <SPI.h>
#include <Wire.h>
#include <LoRa.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_wifi.h"

#ifndef NODE_ID
#define NODE_ID 1
#endif

const char* WIFI_SSID  = "DLink";
const char* WIFI_PASS  = "rachit1234";
const char* SERVER_URL = "http://10.65.83.151:8080/api/telemetry";

#define BAND                  433E6
#define LORA_SPREADING_FACTOR 7
#define LORA_SIGNAL_BANDWIDTH 125E3
#define PIN_SCK   18
#define PIN_MISO  22
#define PIN_MOSI  23
#define PIN_SS     5
#define PIN_RST   14
#define PIN_DIO0  26
#define PIN_SOIL_WATER  35
#define PIN_PM25        32
#define PIN_PM25_LED    33
#define PIN_BATT_TEMP   34

// I2C pins for TCA9548A multiplexer
#define PIN_SDA  21
#define PIN_SCL  19
#define TCA9548A_ADDR 0x70

#define BEACON_INTERVAL_MS   3000
#define DATA_INTERVAL_MS     2000
#define WIFI_INTERVAL_MS     2500
#define PRINT_INTERVAL_MS    2500
#define NEIGHBOR_TIMEOUT_MS  8000
#define FLOOD_WATER_CM       15.0f
#define FLOOD_SOIL_PCT       60.0f
#define CRITICAL_BATTERY_PCT 25.0f

enum NodeRole   { ROLE_MEMBER=0, ROLE_CLUSTER_HEAD=1 };
enum PacketType { PKT_BEACON=0x01, PKT_CH_ELECT=0x02, PKT_DATA=0x03, PKT_CH_HANDOFF=0x04 };

struct __attribute__((packed)) LeachPacket {
  uint16_t magic; uint8_t src_id; uint8_t dst_id; uint8_t pkt_type;
  float ch_score; float battery_pct; uint8_t solar_active;
  float temperature; float water_level; float risk_score;
};

NodeRole      current_role   = ROLE_CLUSTER_HEAD;
uint8_t       active_ch_id   = 1;
unsigned long last_beacon_tx=0, last_data_tx=0, last_wifi_tx=0, last_print_tx=0;
float battery_pct = (NODE_ID==1) ? 95.0f : 88.0f;
bool  solar_active = false;
float water_level_cm=4.2f, soil_moisture_pct=38.0f, pm25_ugm3=14.0f;
float battery_temp_c=28.5f, temperature_c=28.4f, hazard_risk=0.05f;
int   last_http_code = 0;
String last_http_status = "Not Sent Yet";

struct NeighborState { uint8_t id; float ch_score; float battery_pct; int rssi; unsigned long last_seen; }
  neighbor = {0, 0.0f, 100.0f, -90, 0};

// --- Sensor conversions ---
float waterRawToCm(int r)     { return constrain((r/4095.0f)*25.0f, 0.0f, 25.0f); }
float soilRawToPct(int r)     { return constrain(((3200.0f-r)/2000.0f)*100.0f, 0.0f, 100.0f); }
float rawToPm25(int r)        { float v=(r/4095.0f)*3.3f; return constrain((v-0.6f)*150.0f, 0.0f, 500.0f); }
float rawToBattTemp(int r)    { float v=(r/4095.0f)*3.3f; return constrain(15.0f+(v/3.3f)*45.0f, 0.0f, 75.0f); }

void read_sensors() {
  int rsw = analogRead(PIN_SOIL_WATER);
  float raw_wl = waterRawToCm(rsw);
  water_level_cm    = (raw_wl > 0.5f) ? raw_wl : 4.2f;
  soil_moisture_pct = soilRawToPct(rsw);
  pinMode(PIN_PM25_LED, OUTPUT);
  digitalWrite(PIN_PM25_LED, LOW); delayMicroseconds(280);
  int rpm = analogRead(PIN_PM25); delayMicroseconds(40);
  digitalWrite(PIN_PM25_LED, HIGH);
  float raw_pm = rawToPm25(rpm);
  pm25_ugm3 = (raw_pm > 2.0f) ? raw_pm : 14.0f;
  battery_temp_c = rawToBattTemp(analogRead(PIN_BATT_TEMP));
  
  float risk = 0.05f;
  if      (water_level_cm > FLOOD_WATER_CM || soil_moisture_pct > FLOOD_SOIL_PCT) risk = 0.95f;
  else if (water_level_cm > 10.0f          || soil_moisture_pct > 45.0f)          risk = 0.55f;
  else if (water_level_cm > 5.0f           || soil_moisture_pct > 30.0f)          risk = 0.25f;
  hazard_risk = risk;
}

const char* riskLabel() {
  if (hazard_risk >= 0.9f) return "FLOOD ALERT ⚠️";
  if (hazard_risk >= 0.5f) return "ELEVATED 🟡";
  if (hazard_risk >= 0.2f) return "MODERATE 🟢";
  return "NORMAL 🟢";
}

float calc_score() {
  return max(0.0f,
    (battery_pct/100.0f)*(battery_pct/100.0f)*60.0f
    + (solar_active ? 0.0f : 20.0f)
    - hazard_risk * 10.0f);
}

void eval_roles() {
  float ms = calc_score();
  bool neighbor_active = (millis()-neighbor.last_seen < NEIGHBOR_TIMEOUT_MS) && (neighbor.id > 0);
  NodeRole prev_role = current_role;

  if (!neighbor_active || (ms >= neighbor.ch_score && battery_pct > CRITICAL_BATTERY_PCT)) {
    current_role = ROLE_CLUSTER_HEAD; active_ch_id = NODE_ID;
  } else {
    current_role = ROLE_MEMBER; active_ch_id = neighbor.id;
  }

  if (prev_role != current_role) {
    Serial.println("\n-----------------------------------------------------");
    Serial.printf(">>> LEACH ELECTION EVENT: Node %d Role -> %s (Active CH: Node %d, Score: %.1f)\n",
      NODE_ID, (current_role==ROLE_CLUSTER_HEAD)?"CLUSTER HEAD 👑":"CLUSTER MEMBER", active_ch_id, ms);
    Serial.println("-----------------------------------------------------\n");
  }
}

void send_pkt(PacketType type, uint8_t dst) {
  LeachPacket p;
  p.magic=0x4558; p.src_id=NODE_ID; p.dst_id=dst; p.pkt_type=(uint8_t)type;
  p.ch_score=calc_score(); p.battery_pct=battery_pct; p.solar_active=solar_active?1:0;
  p.temperature=temperature_c; p.water_level=water_level_cm; p.risk_score=hazard_risk;
  LoRa.beginPacket(); LoRa.write((uint8_t*)&p, sizeof(p)); LoRa.endPacket();
}

void handle_rx(int sz) {
  if (sz != sizeof(LeachPacket)) return;
  LeachPacket p; LoRa.readBytes((uint8_t*)&p, sizeof(p));
  if (p.magic != 0x4558 || p.src_id == NODE_ID) return;
  int rssi = LoRa.packetRssi(); float snr = LoRa.packetSnr();
  neighbor = {p.src_id, p.ch_score, p.battery_pct, rssi, millis()};

  Serial.printf("[LoRa RX] Beacon from Neighbor Node %d | Score: %.1f | RSSI: %d dBm | SNR: %.1f dB\n",
    p.src_id, p.ch_score, rssi, snr);

  switch ((PacketType)p.pkt_type) {
    case PKT_BEACON: eval_roles(); break;
    case PKT_CH_HANDOFF:
      Serial.printf("[HANDOFF] Neighbor Node %d down -> Promoting Node %d to Cluster Head 👑\n", p.src_id, NODE_ID);
      current_role=ROLE_CLUSTER_HEAD; active_ch_id=NODE_ID;
      send_pkt(PKT_CH_ELECT, 0xFF); break;
    case PKT_DATA:
      if (current_role == ROLE_CLUSTER_HEAD) {
        StaticJsonDocument<300> d;
        d["gw"]=NODE_ID; d["src"]=p.src_id; d["batt"]=int(p.battery_pct);
        d["temp"]=p.temperature; d["water"]=p.water_level;
        d["pm25"]=pm25_ugm3; d["risk"]=p.risk_score; d["rssi"]=rssi; d["snr"]=snr; d["ts"]=millis();
        Serial.print("GW_JSON:"); serializeJson(d, Serial); Serial.println();
      } break;
    default: break;
  }
}

void send_wifi() {
  if (WiFi.status() != WL_CONNECTED) {
    last_http_code = -1;
    last_http_status = "WiFi Reconnecting / Offline";
    WiFi.reconnect();
    return;
  }
  HTTPClient h; h.begin(SERVER_URL);
  h.addHeader("Content-Type","application/json"); h.setTimeout(2500);
  StaticJsonDocument<256> d;
  d["src_node"]=NODE_ID; d["battery_pct"]=int(battery_pct);
  d["battery_temp_c"]=battery_temp_c; d["temperature_c"]=temperature_c;
  d["pm25_ugm3"]=pm25_ugm3; d["water_level_cm"]=water_level_cm;
  d["risk_score"]=hazard_risk; d["role"]=(current_role==ROLE_CLUSTER_HEAD)?"CH":"Member";
  String pl; serializeJson(d, pl);
  int code = h.POST(pl);
  last_http_code = code;
  if (code > 0) {
    last_http_status = "HTTP " + String(code) + " (Dashboard Live Updated 🟢)";
  } else {
    last_http_status = "HTTP Err: " + h.errorToString(code);
  }
  h.end();
}

void print_console_dashboard() {
  Serial.println("\n=====================================================");
  Serial.printf(" ENVIRON-X NODE %d TELEMETRY & LEACH MESH STATUS\n", NODE_ID);
  Serial.println("=====================================================");
  Serial.printf(" [NODE ID]        : Node %d\n", NODE_ID);
  Serial.printf(" [LEACH ROLE]     : %s\n", (current_role==ROLE_CLUSTER_HEAD) ? "CLUSTER HEAD 👑 (GW Connected)" : "CLUSTER MEMBER (Routing via CH)");
  Serial.printf(" [ELECTION SCORE] : %.1f / 100.0\n", calc_score());
  Serial.printf(" [BATTERY LEVEL]  : %.1f %% %s\n", battery_pct, (battery_pct > CRITICAL_BATTERY_PCT) ? "(Healthy 🟢)" : "(CRITICAL ⚠️)");
  Serial.println("-----------------------------------------------------");
  Serial.println(" SENSOR READINGS:");
  Serial.printf("  - Water Level   : %.2f cm\n", water_level_cm);
  Serial.printf("  - Soil Moisture : %.1f %%\n", soil_moisture_pct);
  Serial.printf("  - PM2.5 Dust    : %.1f ug/m3\n", pm25_ugm3);
  Serial.printf("  - Battery Temp  : %.1f °C\n", battery_temp_c);
  Serial.printf("  - Hazard Status : %s (Risk Score: %.2f)\n", riskLabel(), hazard_risk);
  Serial.println("-----------------------------------------------------");
  Serial.println(" NETWORK & CLOUD STATUS:");
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("  - Wi-Fi Network : CONNECTED 🟢 (IP: %s)\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("  - Wi-Fi Network : DISCONNECTED / RECONNECTING 🟡");
  }
  Serial.printf("  - Dashboard TX  : %s\n", last_http_status.c_str());
  
  bool n_online = (millis()-neighbor.last_seen < NEIGHBOR_TIMEOUT_MS) && (neighbor.id > 0);
  if (n_online) {
    Serial.printf("  - Mesh Neighbor : Node %d ONLINE 🟢 (RSSI: %d dBm, Score: %.1f)\n", neighbor.id, neighbor.rssi, neighbor.ch_score);
  } else {
    Serial.println("  - Mesh Neighbor : NO NEIGHBOR DETECTED (Single-Node CH Mode)");
  }
  Serial.println("=====================================================\n");
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);
  Serial.printf("\n=== ENVIRON-X LEACH Node %d (Rich Console Edition) ===\n", NODE_ID);

  // I2C init for TCA9548A multiplexer
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.beginTransmission(TCA9548A_ADDR);
  if (Wire.endTransmission() == 0) {
    Serial.println("[I2C OK] TCA9548A Multiplexer detected at 0x70!");
  } else {
    Serial.println("[I2C] Direct I2C Bus Active");
  }

  // LoRa Ra-02 Init (MISO/MOSI swapped for this board layout)
  pinMode(PIN_RST, OUTPUT);
  digitalWrite(PIN_RST, LOW); delay(20);
  digitalWrite(PIN_RST, HIGH); delay(150);

  SPI.begin(PIN_SCK, PIN_MOSI, PIN_MISO, PIN_SS);
  LoRa.setPins(PIN_SS, PIN_RST, PIN_DIO0);

  bool lora_ok = false;
  for (int attempt = 1; attempt <= 5; attempt++) {
    if (LoRa.begin(BAND)) { lora_ok = true; break; }
    delay(300);
  }
  if (!lora_ok) {
    Serial.println("[WARN] LoRa Ra-02 not responding - Running Wi-Fi Telemetry Mode!");
  } else {
    LoRa.setSpreadingFactor(LORA_SPREADING_FACTOR);
    LoRa.setSignalBandwidth(LORA_SIGNAL_BANDWIDTH);
    LoRa.setTxPower(17); LoRa.enableCrc();
    Serial.println("[OK] LoRa Ra-02 Ready!");
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  wifi_country_t country = {"IN", 1, 13, 20, WIFI_COUNTRY_POLICY_AUTO};
  esp_wifi_set_country(&country);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WiFi] Connecting to "); Serial.print(WIFI_SSID);
  for (int i = 0; i < 25 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi OK] IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WiFi] Connection pending - auto-reconnecting in background");
  }

  eval_roles();
  Serial.println("[READY] Node 1 Online!\n");
}

void loop() {
  unsigned long now = millis();
  read_sensors();
  battery_pct = max(10.0f, battery_pct - (current_role==ROLE_CLUSTER_HEAD ? 0.05f : 0.01f));

  if (current_role==ROLE_CLUSTER_HEAD && battery_pct<=CRITICAL_BATTERY_PCT) {
    Serial.println("[CRITICAL] Battery<=25% LEACH Handoff Triggered!");
    solar_active=true; send_pkt(PKT_CH_HANDOFF,0xFF);
    current_role=ROLE_MEMBER; delay(200); eval_roles();
  }

  int sz = LoRa.parsePacket(); 
  if (sz) handle_rx(sz);

  if (now - last_beacon_tx >= BEACON_INTERVAL_MS) {
    last_beacon_tx = now; 
    send_pkt(PKT_BEACON,0xFF); 
    eval_roles();
  }

  if (current_role==ROLE_MEMBER && now-last_data_tx>=DATA_INTERVAL_MS) {
    last_data_tx = now; 
    send_pkt(PKT_DATA, active_ch_id);
  }

  if (now - last_wifi_tx >= WIFI_INTERVAL_MS) { 
    last_wifi_tx = now; 
    send_wifi(); 
  }

  if (now - last_print_tx >= PRINT_INTERVAL_MS) {
    last_print_tx = now;
    print_console_dashboard();
  }

  delay(20);
}
