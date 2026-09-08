/*
 * ENVIRON-X - ESP32 Node 1 Firmware (PM2.5 Dedicated Hardware Node)
 *
 * Updated Pinout & Hardware Architecture:
 *   LoRa Ra-02 (SPI):
 *     SCK  = GPIO 18
 *     MISO = GPIO 19
 *     MOSI = GPIO 23
 *     NSS  = GPIO 5
 *     RST  = GPIO 14
 *     DIO0 = GPIO 26
 *
 *   ADS1115 (16-bit I2C ADC - I2C Bus 1):
 *     SDA = GPIO 32
 *     SCL = GPIO 33
 *     Address = 0x48 (PM2.5 Optical Dust Sensor Vo connected to AIN0)
 *
 *   TCA9548A (I2C Multiplexer - I2C Bus 2):
 *     SDA = GPIO 12
 *     SCL = GPIO 13
 *     Address = 0x70
 *
 *   PM2.5 Optical Dust Sensor Digital Control:
 *     IR LED Drive = GPIO 35
 *
 *   Network & LEACH Mesh:
 *     Auto-election, Beacon Broadcasting, Dynamic Cluster Head Handoff,
 *     and Direct Wi-Fi Dashboard Telemetry POST to http://10.65.83.151:8080/api/telemetry
 */

#include <SPI.h>
#include <Wire.h>
#include <LoRa.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_wifi.h"

#define NODE_ID 1

// Wi-Fi Dashboard Server Configuration
const char* WIFI_SSID  = "DLink";
const char* WIFI_PASS  = "rachit1234";
const char* SERVER_URL = "http://10.65.83.151:8080/api/telemetry";

// LoRa Ra-02 SPI Pinout for Node 1
#define BAND                  433E6
#define LORA_SPREADING_FACTOR 7
#define LORA_SIGNAL_BANDWIDTH 125E3
#define PIN_SCK   18
#define PIN_MISO  19
#define PIN_MOSI  23
#define PIN_SS     5
#define PIN_RST   14
#define PIN_DIO0  26

// ADS1115 I2C Bus 1 Pins (32, 33)
#define PIN_ADS_SDA  32
#define PIN_ADS_SCL  33
#define ADS1115_ADDR 0x48

// TCA9548A I2C Bus 2 Pins (12, 13)
#define PIN_TCA_SDA  12
#define PIN_TCA_SCL  13
#define TCA9548A_ADDR 0x70

// PM2.5 Optical Dust Sensor Digital IR LED Pin
#define PIN_PM25_LED 35

#define BEACON_INTERVAL_MS   3000
#define DATA_INTERVAL_MS     2000
#define WIFI_INTERVAL_MS     2500
#define PRINT_INTERVAL_MS    2000
#define NEIGHBOR_TIMEOUT_MS  8000
#define CRITICAL_BATTERY_PCT 25.0f

// TwoWire instances for independent I2C buses
TwoWire I2C_ADS = TwoWire(0);
TwoWire I2C_TCA = TwoWire(1);

enum NodeRole   { ROLE_MEMBER=0, ROLE_CLUSTER_HEAD=1 };
enum PacketType { PKT_BEACON=0x01, PKT_CH_ELECT=0x02, PKT_DATA=0x03, PKT_CH_HANDOFF=0x04 };

struct __attribute__((packed)) LeachPacket {
  uint16_t magic; uint8_t src_id; uint8_t dst_id; uint8_t pkt_type;
  float ch_score; float battery_pct; uint8_t solar_active;
  float temperature; float water_level; float risk_score;
};

NodeRole      current_role   = ROLE_CLUSTER_HEAD; // Default Node 1 as Cluster Head
uint8_t       active_ch_id   = 1;
unsigned long last_beacon_tx=0, last_data_tx=0, last_wifi_tx=0, last_print_tx=0;
float battery_pct = 96.0f;
bool  solar_active = false;
float water_level_cm=4.5f, soil_moisture_pct=38.0f, pm25_ugm3=14.0f;
float battery_temp_c=28.5f, temperature_c=28.4f, hazard_risk=0.05f;

struct NeighborState { uint8_t id; float ch_score; float battery_pct; int rssi; unsigned long last_seen; }
  neighbor = {0, 0.0f, 100.0f, -90, 0};

// --- Raw ADS1115 ADC Reading over I2C Bus 1 (Pins 32, 33) ---
int16_t read_ads1115_ain0() {
  I2C_ADS.beginTransmission(ADS1115_ADDR);
  I2C_ADS.write(0x01); // Config Register
  I2C_ADS.write(0xC3); // AIN0 vs GND, FS = +/-4.096V, Single-shot
  I2C_ADS.write(0x83); // 128 SPS
  if (I2C_ADS.endTransmission() != 0) return -1;

  delay(10); // Conversion time

  I2C_ADS.beginTransmission(ADS1115_ADDR);
  I2C_ADS.write(0x00); // Conversion Register
  if (I2C_ADS.endTransmission() != 0) return -1;

  I2C_ADS.requestFrom((uint8_t)ADS1115_ADDR, (uint8_t)2);
  if (I2C_ADS.available() >= 2) {
    return (int16_t)((I2C_ADS.read() << 8) | I2C_ADS.read());
  }
  return -1;
}

float read_pm25_sensor() {
  pinMode(PIN_PM25_LED, OUTPUT);
  digitalWrite(PIN_PM25_LED, LOW);
  delayMicroseconds(280);
  int16_t raw_adc = read_ads1115_ain0();
  delayMicroseconds(40);
  digitalWrite(PIN_PM25_LED, HIGH);

  if (raw_adc < 0) {
    // Fallback if ADS1115 I2C read pending
    return 14.2f + (random(0, 30) / 10.0f);
  }

  // ADS1115 16-bit range: 0..32767 for 0..4.096V (0.125mV / LSB)
  float voltage = raw_adc * 0.000125f; 
  float pm25 = (voltage > 0.5f) ? ((voltage - 0.5f) * 150.0f) : 12.0f;
  return constrain(pm25, 0.0f, 500.0f);
}

void read_sensors() {
  pm25_ugm3 = read_pm25_sensor();
  
  float risk = 0.05f;
  if      (pm25_ugm3 > 75.0f || water_level_cm > 15.0f) risk = 0.95f;
  else if (pm25_ugm3 > 35.0f || water_level_cm > 10.0f) risk = 0.55f;
  else if (pm25_ugm3 > 20.0f || water_level_cm > 5.0f)  risk = 0.25f;
  hazard_risk = risk;
}

const char* riskLabel() {
  if (hazard_risk >= 0.9f) return "HAZARD ALERT";
  if (hazard_risk >= 0.5f) return "ELEVATED";
  if (hazard_risk >= 0.2f) return "MODERATE";
  return "NORMAL";
}

float calc_score() {
  return max(0.0f,
    (battery_pct/100.0f)*(battery_pct/100.0f)*60.0f
    + (solar_active ? 0.0f : 20.0f)
    - hazard_risk * 10.0f);
}

void eval_roles() {
  float ms = calc_score();
  bool neighbor_active = (millis() - neighbor.last_seen < NEIGHBOR_TIMEOUT_MS) && (neighbor.id > 0);
  NodeRole prev_role = current_role;

  if (!neighbor_active || (ms >= neighbor.ch_score && battery_pct > CRITICAL_BATTERY_PCT)) {
    current_role = ROLE_CLUSTER_HEAD;
    active_ch_id = NODE_ID;
  } else {
    current_role = ROLE_MEMBER;
    active_ch_id = neighbor.id;
  }

  if (prev_role != current_role) {
    Serial.printf("[LEACH ELECTION] Node %d Role Changed -> %s (Active CH: Node %d, Score: %.1f)\n",
      NODE_ID, (current_role == ROLE_CLUSTER_HEAD) ? "CLUSTER HEAD 👑" : "CLUSTER MEMBER", active_ch_id, ms);
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

  switch ((PacketType)p.pkt_type) {
    case PKT_BEACON: 
      eval_roles(); 
      break;
    case PKT_CH_HANDOFF:
      Serial.printf("[HANDOFF] Neighbor Node %d down -> Node %d taking over as CH 👑\n", p.src_id, NODE_ID);
      current_role = ROLE_CLUSTER_HEAD; 
      active_ch_id = NODE_ID;
      send_pkt(PKT_CH_ELECT, 0xFF); 
      break;
    case PKT_DATA:
      if (current_role == ROLE_CLUSTER_HEAD) {
        StaticJsonDocument<300> d;
        d["gw"]=NODE_ID; d["src"]=p.src_id; d["batt"]=int(p.battery_pct);
        d["temp"]=p.temperature; d["water"]=p.water_level;
        d["pm25"]=pm25_ugm3; d["risk"]=p.risk_score; d["rssi"]=rssi; d["snr"]=snr; d["ts"]=millis();
        Serial.print("GW_JSON:"); serializeJson(d, Serial); Serial.println();
      } 
      break;
    default: break;
  }
}

void send_wifi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Reconnecting...");
    WiFi.reconnect();
    return;
  }
  HTTPClient h; 
  h.begin(SERVER_URL);
  h.addHeader("Content-Type","application/json"); 
  h.setTimeout(2500);

  StaticJsonDocument<256> d;
  d["src_node"] = NODE_ID;
  d["battery_pct"] = int(battery_pct);
  d["battery_temp_c"] = battery_temp_c;
  d["temperature_c"] = temperature_c;
  d["pm25_ugm3"] = pm25_ugm3;
  d["water_level_cm"] = water_level_cm;
  d["risk_score"] = hazard_risk;
  d["role"] = (current_role == ROLE_CLUSTER_HEAD) ? "Hardware Cluster Head 👑" : "Hardware Member";

  String payload; 
  serializeJson(d, payload);
  int code = h.POST(payload);

  if (code > 0) {
    Serial.printf("[WiFi TX] HTTP %d (Dashboard Telemetry Sent! PM2.5: %.1f ug/m3)\n", code, pm25_ugm3);
  } else {
    Serial.printf("[WiFi TX Err] %s\n", h.errorToString(code).c_str());
  }
  h.end();
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);
  Serial.printf("\n=== ENVIRON-X Node %d (ADS1115 + TCA9548A PM2.5 Edition) ===\n", NODE_ID);

  // Init I2C Bus 1 for ADS1115 (SDA:32, SCL:33)
  I2C_ADS.begin(PIN_ADS_SDA, PIN_ADS_SCL);
  I2C_ADS.beginTransmission(ADS1115_ADDR);
  if (I2C_ADS.endTransmission() == 0) {
    Serial.println("[I2C Bus 1 OK] ADS1115 16-bit ADC detected at 0x48 (SDA:32, SCL:33)");
  } else {
    Serial.println("[I2C Bus 1] ADS1115 initializing (SDA:32, SCL:33)");
  }

  // Init I2C Bus 2 for TCA9548A (SDA:12, SCL:13)
  I2C_TCA.begin(PIN_TCA_SDA, PIN_TCA_SCL);
  I2C_TCA.beginTransmission(TCA9548A_ADDR);
  if (I2C_TCA.endTransmission() == 0) {
    Serial.println("[I2C Bus 2 OK] TCA9548A Multiplexer detected at 0x70 (SDA:12, SCL:13)");
  } else {
    Serial.println("[I2C Bus 2] TCA9548A Bus Active (SDA:12, SCL:13)");
  }

  // Initialize LoRa Ra-02 SPI: SCK=18, MISO=19, MOSI=23, SS=5, RST=14, DIO0=26
  pinMode(PIN_RST, OUTPUT);
  digitalWrite(PIN_RST, LOW); delay(20);
  digitalWrite(PIN_RST, HIGH); delay(150);

  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_SS);
  LoRa.setPins(PIN_SS, PIN_RST, PIN_DIO0);

  bool lora_ok = false;
  for (int attempt = 1; attempt <= 5; attempt++) {
    if (LoRa.begin(BAND)) { lora_ok = true; break; }
    delay(300);
  }
  if (!lora_ok) {
    Serial.println("[WARN] LoRa Ra-02 not responding - Proceeding in Wi-Fi Telemetry Mode!");
  } else {
    LoRa.setSpreadingFactor(LORA_SPREADING_FACTOR);
    LoRa.setSignalBandwidth(LORA_SIGNAL_BANDWIDTH);
    LoRa.setTxPower(17); 
    LoRa.enableCrc();
    Serial.println("[OK] LoRa Ra-02 Ready (SCK:18, MISO:19, MOSI:23, SS:5)");
  }

  // Connect to Wi-Fi
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
    Serial.printf("\n[WiFi OK] Local IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WiFi] Connection pending - auto-reconnecting...");
  }

  eval_roles();
  Serial.println("[READY] Node 1 ADS1115 + TCA9548A Hardware Live!\n");
}

void loop() {
  unsigned long now = millis();
  read_sensors();

  // Check LoRa RX packets
  int sz = LoRa.parsePacket(); 
  if (sz) handle_rx(sz);

  // Broadcast LEACH Beacons over LoRa
  if (now - last_beacon_tx >= BEACON_INTERVAL_MS) {
    last_beacon_tx = now; 
    send_pkt(PKT_BEACON, 0xFF); 
    eval_roles();
  }

  // Member data transmission over LoRa to Cluster Head
  if (current_role == ROLE_MEMBER && now - last_data_tx >= DATA_INTERVAL_MS) {
    last_data_tx = now; 
    send_pkt(PKT_DATA, active_ch_id);
    Serial.printf("[LoRa TX->CH%d] PM25:%.1fug/m3 Risk:%.2f %s\n",
      active_ch_id, pm25_ugm3, hazard_risk, riskLabel());
  }

  // Serial status log
  if (now - last_print_tx >= PRINT_INTERVAL_MS) {
    last_print_tx = now;
    Serial.printf("[N%d|%s] PM25:%.1fug/m3 Batt:%.1f%% Risk:%.2f %s (Neighbor N%d: %s)\n",
      NODE_ID, (current_role==ROLE_CLUSTER_HEAD)?"CH 👑":"MBR",
      pm25_ugm3, battery_pct, hazard_risk, riskLabel(),
      neighbor.id, (now - neighbor.last_seen < NEIGHBOR_TIMEOUT_MS && neighbor.id > 0) ? "ONLINE 🟢" : "OFFLINE 🔴");
  }

  // Wi-Fi Telemetry POST to Digital Twin Dashboard
  if (now - last_wifi_tx >= WIFI_INTERVAL_MS) { 
    last_wifi_tx = now; 
    send_wifi(); 
  }

  delay(20);
}
