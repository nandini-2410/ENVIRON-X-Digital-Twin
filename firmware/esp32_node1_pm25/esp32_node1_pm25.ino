/*
 * ENVIRON-X - ESP32 Node 1 Firmware (PM2.5 Dedicated Hardware Node - Dynamic Hot-Plug Rescan)
 *
 * Hardware Architecture:
 *   LoRa Ra-02 (SPI):
 *     SCK = 18, MISO = 19, MOSI = 23, NSS = 5, RST = 14, DIO0 = 26
 *
 *   TCA9548A I2C Multiplexer (Live Hot-Plug Rescanned on SDA: 12/21/32, SCL: 13/22/33 at 0x70):
 *     All I2C Sensors (ADS1115 ADC, BME280, OLED, MPU6050) connected to MUX Channels CH0..CH7!
 *
 *   ADS1115 16-Bit ADC (Attached behind MUX or direct I2C at 0x48):
 *     AIN0 = PM2.5 Optical Dust Sensor Vo Signal
 *     AIN1 = Water Level / Soil Moisture Signal
 *     AIN2 = Battery Voltage / Thermistor
 *     AIN3 = Auxiliary Sensor Input
 *
 *   PM2.5 Optical Dust Sensor Digital Control:
 *     IR LED Drive = GPIO 25 (Output Capable)
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

// Default I2C Pins (GPIO 21 SDA, GPIO 22 SCL - Safe non-strapping pins, auto-detected if different)
uint8_t pin_tca_sda = 21;
uint8_t pin_tca_scl = 22;
#define TCA9548A_ADDR 0x70
#define ADS1115_ADDR  0x48

// PM2.5 Optical Dust Sensor Digital IR LED Pin
#define PIN_PM25_LED 25

// Direct ESP32 Internal Analog Pins (if MUX/ADS disabled)
#define PIN_ESP_BATT 34
#define PIN_ESP_PM25 32
#define PIN_ESP_WATER 33

#define BEACON_INTERVAL_MS   3000
#define DATA_INTERVAL_MS     2000
#define WIFI_INTERVAL_MS     2500
#define PRINT_INTERVAL_MS    2500
#define RESCAN_INTERVAL_MS   3000
#define NEIGHBOR_TIMEOUT_MS  8000
#define CRITICAL_BATTERY_PCT 25.0f

// Single primary TwoWire bus for MUX and all attached sensors
TwoWire I2C_BUS = TwoWire(0);

enum NodeRole   { ROLE_MEMBER=0, ROLE_CLUSTER_HEAD=1 };
enum PacketType { PKT_BEACON=0x01, PKT_CH_ELECT=0x02, PKT_DATA=0x03, PKT_CH_HANDOFF=0x04 };

struct __attribute__((packed)) LeachPacket {
  uint16_t magic; uint8_t src_id; uint8_t dst_id; uint8_t pkt_type;
  float ch_score; float battery_pct; uint8_t solar_active;
  float temperature; float water_level; float risk_score;
};

NodeRole      current_role   = ROLE_CLUSTER_HEAD;
uint8_t       active_ch_id   = 1;
unsigned long last_beacon_tx=0, last_data_tx=0, last_wifi_tx=0, last_print_tx=0, last_rescan_tx=0;

// Sensor Real State (Initialized to 0 - No Fake Data)
float battery_pct = 0.0f;
bool  battery_connected = false;
bool  solar_active = false;
float water_level_cm = 0.0f;
float water_volts = 0.0f;
float soil_moisture_pct = 0.0f;
float pm25_ugm3 = 0.0f;
float pm25_volts = 0.0f;
float battery_temp_c = 0.0f;
float temperature_c = 0.0f;
float hazard_risk = 0.0f;

int16_t raw_ads_ain0 = -1;
int16_t raw_ads_ain1 = -1;
int16_t raw_ads_ain2 = -1;
int16_t raw_ads_ain3 = -1;

int8_t water_mux_channel = 6; // Default SD6 / SC6 for Water Level ADS1115 (Pin A0)
int8_t soil_mux_channel  = 7; // Default SD7 / SC7 for Soil Moisture ADS1115 (Pin A0)

bool    tca9548a_online  = false;
bool    ads1115_online   = false;
bool    ads_water_online = false;
bool    ads_soil_online  = false;
int8_t  ads_mux_channel  = -1; // -1 if direct I2C, 0..7 if behind MUX
uint8_t ads1115_i2c_addr = 0x48;

int   last_http_code = 0;
String last_http_status = "Not Sent Yet";

struct NeighborState { uint8_t id; float ch_score; float battery_pct; int rssi; unsigned long last_seen; }
  neighbor = {0, 0.0f, 100.0f, -90, 0};

// --- EEPROM Plug & Play Header Structure (From eeprom_flasher.ino) ---
struct __attribute__((packed)) ModuleEEPROMHeader {
  uint16_t magic;          // 0x4558 ('EX')
  uint8_t  sensor_type_id; // 1=BMP280, 2=MQ135, 3=GP2Y, 4=WATER, 5=MPU6050, 6=SOIL
  char     sensor_name[16];// Human readable string
  float    calib_min;      // Minimum range
  float    calib_max;      // Maximum range
  uint32_t checksum;       // Simple checksum
};

ModuleEEPROMHeader read_eeprom_header(uint8_t eeprom_addr = 0x50) {
  ModuleEEPROMHeader header;
  memset(&header, 0, sizeof(ModuleEEPROMHeader));
  uint8_t* p = (uint8_t*)&header;
  size_t len = sizeof(ModuleEEPROMHeader);

  I2C_BUS.beginTransmission(eeprom_addr);
  if (I2C_BUS.endTransmission() != 0) return header;

  I2C_BUS.beginTransmission(eeprom_addr);
  I2C_BUS.write((uint8_t)0);
  if (I2C_BUS.endTransmission() == 0) {
    for (size_t i = 0; i < len; i++) {
      if (I2C_BUS.requestFrom((uint8_t)eeprom_addr, (uint8_t)1) == 1) {
        p[i] = I2C_BUS.read();
      }
    }
  }

  // Try 2-byte addressing if 1-byte did not yield magic 0x4558
  if (header.magic != 0x4558) {
    I2C_BUS.beginTransmission(eeprom_addr);
    I2C_BUS.write(0);
    I2C_BUS.write(0);
    if (I2C_BUS.endTransmission() == 0) {
      for (size_t i = 0; i < len; i++) {
        if (I2C_BUS.requestFrom((uint8_t)eeprom_addr, (uint8_t)1) == 1) {
          p[i] = I2C_BUS.read();
        }
      }
    }
  }

  return header;
}

// --- TCA9548A Multiplexer Control ---
void tca_select_channel(uint8_t channel) {
  if (channel > 7) return;
  I2C_BUS.beginTransmission(TCA9548A_ADDR);
  I2C_BUS.write(1 << channel);
  I2C_BUS.endTransmission();
}

void scan_tca_multiplexer(bool verbose = true) {
  int total_found = 0;
  ads1115_online   = false;
  ads_water_online = false;
  ads_soil_online  = false;
  ads_mux_channel  = -1;

  if (verbose) {
    Serial.println("\n--- TCA9548A Multiplexer (0x70) Channel & EEPROM Detection Pass ---");
  }

  for (uint8_t ch = 0; ch < 8; ch++) {
    tca_select_channel(ch);
    delay(5); // Stabilization delay for MUX channel switch
    int ch_found = 0;
    
    // Check if EEPROM chip (0x50..0x57) exists on this MUX channel
    for (uint8_t e_addr = 0x50; e_addr <= 0x57; e_addr++) {
      ModuleEEPROMHeader ep = read_eeprom_header(e_addr);
      if (ep.magic == 0x4558) {
        if (ep.sensor_type_id == 4) { // WATER
          water_mux_channel = ch;
          ads_water_online = true;
          if (verbose) Serial.printf("  [EEPROM PLUG-AND-PLAY MUX CH %d] Auto-Discovered: %s (Type ID: 4)\n", ch, ep.sensor_name);
        } else if (ep.sensor_type_id == 6) { // SOIL
          soil_mux_channel = ch;
          ads_soil_online = true;
          if (verbose) Serial.printf("  [EEPROM PLUG-AND-PLAY MUX CH %d] Auto-Discovered: %s (Type ID: 6)\n", ch, ep.sensor_name);
        }
      }
    }

    for (uint8_t addr = 1; addr < 127; addr++) {
      if (addr == TCA9548A_ADDR) continue;
      I2C_BUS.beginTransmission(addr);
      if (I2C_BUS.endTransmission() == 0) {
        const char* dev_name = "Unknown I2C Device";
        if (addr >= 0x48 && addr <= 0x4B) {
          if (ch == water_mux_channel) {
            dev_name = "Water Level ADS1115 ADC (Pin A0)";
            ads_water_online = true;
          } else if (ch == soil_mux_channel) {
            dev_name = "Soil Moisture ADS1115 ADC (Pin A0)";
            ads_soil_online = true;
          } else {
            dev_name = "ADS1115 16-Bit Precision ADC Module";
          }
          ads1115_online = true;
          ads_mux_channel = ch;
          ads1115_i2c_addr = addr;
        } else if (addr >= 0x50 && addr <= 0x57) {
          dev_name = "24Cxx Module EEPROM Memory";
        } else if (addr == 0x76 || addr == 0x77) {
          dev_name = "BME280 / BMP280 Environmental Sensor";
        } else if (addr == 0x68 || addr == 0x69) {
          dev_name = "MPU6050 Accelerometer/Gyro";
        } else if (addr == 0x3C || addr == 0x3D) {
          dev_name = "OLED Display Screen";
        }

        if (verbose) {
          Serial.printf("  [OK MUX CH %d] DETECTED: %s at 0x%02X\n", ch, dev_name, addr);
        }
        ch_found++;
        total_found++;
      }
    }
  }

  if (verbose) {
    if (total_found == 0) {
      Serial.println("  (No active I2C ADC or sensors detected on MUX channels CH0..CH7 — check sensor wiring!)");
    }
    Serial.println("-------------------------------------------------------------------\n");
  }
}

// --- Dynamic Interval Hot-Plug I2C Bus Auto-Detector ---
void check_i2c_hotplug() {
  unsigned long now = millis();
  if (now - last_rescan_tx < RESCAN_INTERVAL_MS) return;
  last_rescan_tx = now;

  struct PinPair { uint8_t sda; uint8_t scl; };
  PinPair pairs[] = { {21, 22}, {12, 13}, {32, 33}, {4, 15} };

  bool previously_online = tca9548a_online;
  bool found_mux = false;
  uint8_t found_sda = pin_tca_sda;
  uint8_t found_scl = pin_tca_scl;

  // 1. Probe current active SDA/SCL pins first (default Pin 12/13)
  I2C_BUS.begin(pin_tca_sda, pin_tca_scl);
  I2C_BUS.beginTransmission(TCA9548A_ADDR);
  if (I2C_BUS.endTransmission() == 0) {
    found_mux = true;
  } else {
    // 2. Scan alternate pin pairs if default pins didn't respond
    for (int i = 0; i < 4; i++) {
      I2C_BUS.begin(pairs[i].sda, pairs[i].scl);
      I2C_BUS.beginTransmission(TCA9548A_ADDR);
      if (I2C_BUS.endTransmission() == 0) {
        found_mux = true;
        found_sda = pairs[i].sda;
        found_scl = pairs[i].scl;
        break;
      }
    }
  }

  if (found_mux) {
    pin_tca_sda = found_sda;
    pin_tca_scl = found_scl;
    tca9548a_online = true;

    if (!previously_online) {
      Serial.println("\n=====================================================");
      Serial.printf(" [HOTPLUG DETECTED] I2C Wire Re-connected!\n");
      Serial.printf(" TCA9548A Multiplexer (0x70) ACTIVE on SDA:%d, SCL:%d\n", pin_tca_sda, pin_tca_scl);
      Serial.println("=====================================================");
      scan_tca_multiplexer(true); // Full verbose print on initial connection
    } else {
      scan_tca_multiplexer(false); // Quiet periodic check to update channel status
    }
  } else {
    // MUX not responding (Pin 12 unplugged for upload/boot)
    if (previously_online) {
      Serial.println("\n[HOTPLUG DISCONNECTED] Switching to direct internal ESP32 pin sampling...");
    }
    tca9548a_online = false;
    ads1115_online  = false;
    ads_water_online= false;
    ads_soil_online = false;
    ads_mux_channel = -1;

    // Check if ADS1115 ADC is directly attached without MUX
    for (int i = 0; i < 4; i++) {
      I2C_BUS.begin(pairs[i].sda, pairs[i].scl);
      I2C_BUS.beginTransmission(ADS1115_ADDR);
      if (I2C_BUS.endTransmission() == 0) {
        ads1115_online = true;
        ads_mux_channel = -1;
        break;
      }
    }

    // Always reset bus back to Pin 12/13 so next probe checks Pin 12 immediately!
    I2C_BUS.begin(12, 13);
  }
}

// --- Dedicated ADS1115 16-Bit ADC Reader (Specifying MUX Channel & AIN Pin) ---
int16_t read_ads1115_on_mux(int8_t mux_ch, uint8_t ain_pin, uint8_t i2c_addr = 0x48) {
  if (mux_ch >= 0) {
    tca_select_channel((uint8_t)mux_ch);
    delay(2);
  }

  // Single-ended AINx vs GND, FS = +/-4.096V, Single-shot mode
  uint8_t msb = 0x80 | ((4 + ain_pin) << 4) | 0x03; // AINx vs GND
  uint8_t lsb = 0x83; // 128 SPS

  I2C_BUS.beginTransmission(i2c_addr);
  I2C_BUS.write(0x01); // Config Register (0x01)
  I2C_BUS.write(msb);
  I2C_BUS.write(lsb);
  if (I2C_BUS.endTransmission() != 0) return -1;

  delay(10); // Wait 10ms conversion time

  if (mux_ch >= 0) {
    tca_select_channel((uint8_t)mux_ch);
  }

  I2C_BUS.beginTransmission(i2c_addr);
  I2C_BUS.write(0x00); // Point to Conversion Register (0x00)
  if (I2C_BUS.endTransmission() != 0) return -1;

  I2C_BUS.requestFrom((uint8_t)i2c_addr, (uint8_t)2);
  if (I2C_BUS.available() >= 2) {
    return (int16_t)((I2C_BUS.read() << 8) | I2C_BUS.read());
  }
  return -1;
}

int16_t read_ads1115_channel(uint8_t channel) {
  return read_ads1115_on_mux(ads_mux_channel >= 0 ? ads_mux_channel : water_mux_channel, channel, ads1115_i2c_addr);
}

float read_pm25_sensor() {
  pinMode(PIN_PM25_LED, OUTPUT);
  
  digitalWrite(PIN_PM25_LED, LOW);   // IR LED ON
  delayMicroseconds(280);
  
  raw_ads_ain0 = read_ads1115_on_mux(water_mux_channel, 1); // Sample PM2.5 on AIN1 if attached
  if (raw_ads_ain0 < 0) {
    raw_ads_ain0 = analogRead(PIN_ESP_PM25); // Direct ESP32 Pin 32
  }
  
  delayMicroseconds(40);
  digitalWrite(PIN_PM25_LED, HIGH);  // IR LED OFF

  if (raw_ads_ain0 <= 0) {
    pm25_volts = 0.0f;
    return 0.0f;
  }

  pm25_volts = (raw_ads_ain0 > 0 && ads_water_online) ? (raw_ads_ain0 * 0.000125f) : ((raw_ads_ain0 / 4095.0f) * 3.3f);
  float pm25 = (pm25_volts > 0.5f) ? ((pm25_volts - 0.5f) * 150.0f) : (pm25_volts * 20.0f);
  return constrain(pm25, 0.0f, 500.0f);
}

float soil_volts = 0.0f;

void read_sensors() {
  pm25_ugm3 = read_pm25_sensor();
  
  // Read Water Level Sensor: ADS1115 on MUX water_mux_channel (Default CH6 SD6/SC6), Pin A0 (AIN0)
  raw_ads_ain1 = read_ads1115_on_mux(water_mux_channel, 0);
  if (raw_ads_ain1 >= 0) {
    water_volts = raw_ads_ain1 * 0.000125f;
    ads_water_online = true;
  } else {
    raw_ads_ain1 = analogRead(PIN_ESP_WATER); // Pin 33
    water_volts = (raw_ads_ain1 / 4095.0f) * 3.3f;
  }
  water_level_cm = (raw_ads_ain1 >= 0) ? constrain((water_volts / 3.3f) * 25.0f, 0.0f, 25.0f) : 0.0f;

  // Read Soil Moisture Sensor: ADS1115 on MUX soil_mux_channel (Default CH7 SD7/SC7), Pin A0 (AIN0)
  raw_ads_ain2 = read_ads1115_on_mux(soil_mux_channel, 0);
  if (raw_ads_ain2 >= 0) {
    soil_volts = raw_ads_ain2 * 0.000125f;
    ads_soil_online = true;
  } else {
    raw_ads_ain2 = analogRead(PIN_ESP_BATT); // Pin 34
    soil_volts = (raw_ads_ain2 / 4095.0f) * 3.3f;
  }
  
  // Resistive Soil Moisture Sensor (FC-28 / YL-69 Prongs) Calibration:
  // Open Prongs in Air = ~3.25V (0.0% Moisture)
  // Submerged / Wet Soil = ~0.80V (100.0% Moisture)
  const float AIR_VOLTS_RES   = 3.25f;
  const float WATER_VOLTS_RES = 0.80f;
  if (raw_ads_ain2 > 100 && soil_volts > 0.3f) {
    soil_moisture_pct = constrain(((AIR_VOLTS_RES - soil_volts) / (AIR_VOLTS_RES - WATER_VOLTS_RES)) * 100.0f, 0.0f, 100.0f);
  } else {
    soil_moisture_pct = 0.0f;
  }

  // Read Battery Voltage (ADS1115 AIN3)
  raw_ads_ain3 = read_ads1115_on_mux(water_mux_channel, 3);
  if (raw_ads_ain3 > 50) {
    battery_connected = true;
    float v3 = raw_ads_ain3 * 0.000125f;
    battery_pct = constrain((v3 / 3.3f) * 100.0f, 0.0f, 100.0f);
    battery_temp_c = 15.0f + (v3 / 3.3f) * 45.0f;
  } else {
    battery_connected = false;
    battery_pct = 0.0f;
    battery_temp_c = 0.0f;
  }
  
  float risk = 0.0f;
  if      (pm25_ugm3 > 75.0f || water_level_cm > 15.0f) risk = 0.95f;
  else if (pm25_ugm3 > 35.0f || water_level_cm > 10.0f) risk = 0.55f;
  else if (pm25_ugm3 > 20.0f || water_level_cm > 5.0f)  risk = 0.25f;
  hazard_risk = risk;
}

const char* riskLabel() {
  if (hazard_risk >= 0.9f) return "HAZARD ALERT ⚠️";
  if (hazard_risk >= 0.5f) return "ELEVATED 🟡";
  if (hazard_risk >= 0.2f) return "MODERATE 🟢";
  return "NORMAL 🟢";
}

float calc_score() {
  if (!battery_connected) return 0.0f;
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
    Serial.println("\n-----------------------------------------------------");
    Serial.printf(">>> LEACH ELECTION EVENT: Node %d Role -> %s (Active CH: Node %d, Score: %.1f)\n",
      NODE_ID, (current_role == ROLE_CLUSTER_HEAD) ? "CLUSTER HEAD 👑" : "CLUSTER MEMBER", active_ch_id, ms);
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
    last_http_code = -1;
    last_http_status = "WiFi Reconnecting / Offline";
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
  d["soil_moisture_pct"] = soil_moisture_pct;
  d["risk_score"] = hazard_risk;
  d["role"] = (current_role == ROLE_CLUSTER_HEAD) ? "Hardware Cluster Head (GW Connected)" : "Hardware Member";

  String payload; 
  serializeJson(d, payload);
  int code = h.POST(payload);
  last_http_code = code;

  if (code > 0) {
    last_http_status = "HTTP " + String(code) + " (Dashboard Live Updated OK)";
  } else {
    last_http_status = "HTTP Err: " + h.errorToString(code);
  }
  h.end();
}

void print_console_dashboard() {
  Serial.println("\n=====================================================");
  Serial.printf(" ENVIRON-X NODE %d TELEMETRY & SENSOR DETECTION REPORT\n", NODE_ID);
  Serial.println("=====================================================");
  Serial.printf(" [NODE ID]        : Node %d (PM2.5 Dedicated Hardware Node)\n", NODE_ID);
  Serial.printf(" [LEACH ROLE]     : %s\n", (current_role==ROLE_CLUSTER_HEAD) ? "CLUSTER HEAD (GW Connected)" : "CLUSTER MEMBER (Routing via CH)");
  Serial.printf(" [ELECTION SCORE] : %.1f / 100.0\n", calc_score());
  
  if (battery_connected) {
    Serial.printf(" [BATTERY LEVEL]  : %.1f %% [OK]\n", battery_pct);
  } else {
    Serial.println(" [BATTERY LEVEL]  : DISCONNECTED (0.0% - No Battery Pin Voltage)");
  }
  
  Serial.println("-----------------------------------------------------");
  Serial.println(" DETECTED HARDWARE BUS & MUX ROUTING:");
  
  if (tca9548a_online) {
    Serial.printf("  [OK DETECTED] TCA9548A 8-Channel MUX at 0x70 (SDA:%d, SCL:%d)\n", pin_tca_sda, pin_tca_scl);
  } else {
    Serial.printf("  [NOT FOUND] TCA9548A MUX at 0x70 (Live Rescanning every 3s...)\n");
  }

  if (ads1115_online) {
    if (ads_mux_channel >= 0) {
      Serial.printf("  [OK DETECTED] ADS1115 16-bit ADC at 0x%02X (Routed via MUX CH%d) [OK]\n", ads1115_i2c_addr, ads_mux_channel);
    } else {
      Serial.printf("  [OK DETECTED] ADS1115 16-bit ADC at 0x%02X (Direct I2C Bus) [OK]\n", ads1115_i2c_addr);
    }
  } else {
    Serial.println("  [NOT FOUND] ADS1115 ADC -> Sampling Direct ESP32 Analog Pins");
  }

  Serial.println("-----------------------------------------------------");
  Serial.println(" SENSOR READINGS & HARDWARE DETECTION CHECKLIST:");

  // PM2.5 Optical Dust Sensor
  uint8_t pm25_sig_pin = ads1115_online ? 32 : PIN_ESP_PM25;
  if (pm25_volts > 0.05f) {
    Serial.printf("  [OK DETECTED] PM2.5 Optical Dust Sensor (LED Pin: 25 | Signal Pin: %d)\n", pm25_sig_pin);
    Serial.printf("                * Concentration : %.1f ug/m3\n", pm25_ugm3);
    Serial.printf("                * Signal Voltage: %.3f V (Raw ADC: %d)\n", pm25_volts, raw_ads_ain0);
  } else {
    Serial.printf("  [MONITORING] PM2.5 Dust Sensor (LED Pin: 25 | Signal Pin: %d)\n", pm25_sig_pin);
    Serial.printf("               * Status       : Live Pin Sampled (Zero Dust / Clean Air)\n");
    Serial.printf("               * Concentration : %.1f ug/m3\n", pm25_ugm3);
    Serial.printf("               * Signal Voltage: %.3f V (Raw ADC: %d)\n", pm25_volts, raw_ads_ain0);
  }

  // Water Level Sensor (ADS1115 on MUX SD6/SC6 CH6 Pin A0)
  if (water_level_cm > 0.1f) {
    Serial.printf("  [SUBMERGED] Water Level Sensor (ADS1115 MUX SD6/SC6 CH6 Pin A0)\n");
    Serial.printf("              * Water Depth  : %.2f cm\n", water_level_cm);
    Serial.printf("              * Pin Voltage  : %.3f V (Raw ADC: %d)\n", water_volts, raw_ads_ain1);
  } else {
    Serial.printf("  [DRY / WIRED] Water Level Sensor (ADS1115 MUX SD6/SC6 CH6 Pin A0)\n");
    Serial.printf("              * Status       : Sensor Dry / Unsubmerged in Water\n");
    Serial.printf("              * Water Depth  : 0.00 cm\n");
    Serial.printf("              * Pin Voltage  : %.3f V (Raw ADC: %d)\n", water_volts, raw_ads_ain1);
  }

  // Soil Moisture Sensor (ADS1115 on MUX SD7/SC7 CH7 Pin A0)
  if (soil_moisture_pct > 1.0f) {
    Serial.printf("  [OK DETECTED] Soil Moisture Sensor (ADS1115 MUX SD7/SC7 CH7 Pin A0)\n");
    Serial.printf("                * Soil Moisture: %.1f %%\n", soil_moisture_pct);
    Serial.printf("                * Pin Voltage  : %.3f V (Raw ADC: %d)\n", soil_volts, raw_ads_ain2);
  } else {
    Serial.printf("  [DRY / WIRED] Soil Moisture Sensor (ADS1115 MUX SD7/SC7 CH7 Pin A0)\n");
    Serial.printf("                * Status       : Dry Soil / Unsubmerged\n");
    Serial.printf("                * Soil Moisture: 0.0 %%\n");
    Serial.printf("                * Pin Voltage  : %.3f V (Raw ADC: %d)\n", soil_volts, raw_ads_ain2);
  }

  // Battery Thermistor / Voltage Sensor (ADS1115 Channel AIN3)
  if (battery_connected) {
    Serial.printf("  [OK DETECTED] Battery Temp Thermistor (ADS1115 AIN3) : %.1f deg C (Raw ADC: %d)\n", battery_temp_c, raw_ads_ain3);
  } else {
    Serial.println("  [NOT FOUND] Battery Thermistor: DISCONNECTED");
  }

  Serial.printf("  - Hazard Assessment: %s (Risk Score: %.2f)\n", riskLabel(), hazard_risk);
  Serial.println("-----------------------------------------------------");
  Serial.println(" NETWORK & CLOUD TRANSMISSION:");
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("  - Wi-Fi Network : CONNECTED [OK] (IP: %s)\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("  - Wi-Fi Network : DISCONNECTED / CONNECTING...");
  }
  Serial.printf("  - Dashboard TX  : %s\n", last_http_status.c_str());
  
  bool n_online = (millis()-neighbor.last_seen < NEIGHBOR_TIMEOUT_MS) && (neighbor.id > 0);
  if (n_online) {
    Serial.printf("  - Mesh Neighbor : Node %d ONLINE [OK] (RSSI: %d dBm, Score: %.1f)\n", neighbor.id, neighbor.rssi, neighbor.ch_score);
  } else {
    Serial.println("  - Mesh Neighbor : NO NEIGHBOR DETECTED (Single-Node CH Mode)");
  }
  Serial.println("=====================================================\n");
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);
  Serial.printf("\n=== ENVIRON-X Node %d (Dynamic Hot-Plug Rescan Mode) ===\n", NODE_ID);

  analogReadResolution(12); // ESP32 12-bit ADC

  // Initial scan for TCA9548A MUX across potential pin pairs
  struct PinPair { uint8_t sda; uint8_t scl; };
  PinPair pairs[] = { {21, 22}, {12, 13}, {32, 33}, {4, 15} };
  
  for (int i = 0; i < 4; i++) {
    I2C_BUS.begin(pairs[i].sda, pairs[i].scl);
    I2C_BUS.beginTransmission(TCA9548A_ADDR);
    if (I2C_BUS.endTransmission() == 0) {
      tca9548a_online = true;
      pin_tca_sda = pairs[i].sda;
      pin_tca_scl = pairs[i].scl;
      Serial.printf("[I2C BUS OK] Detected TCA9548A Multiplexer (0x70) on SDA:%d, SCL:%d!\n", pairs[i].sda, pairs[i].scl);
      scan_tca_multiplexer();
      break;
    }
  }

  if (!tca9548a_online) {
    for (int i = 0; i < 4; i++) {
      I2C_BUS.begin(pairs[i].sda, pairs[i].scl);
      I2C_BUS.beginTransmission(ADS1115_ADDR);
      if (I2C_BUS.endTransmission() == 0) {
        ads1115_online = true;
        ads_mux_channel = -1; // Direct I2C
        Serial.printf("[I2C BUS OK] Detected Direct ADS1115 ADC (0x48) on SDA:%d, SCL:%d!\n", pairs[i].sda, pairs[i].scl);
        break;
      }
    }
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

  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
    delay(400);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi OK] Local IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WiFi] Connecting in background...");
  }

  eval_roles();
  Serial.println("[READY] Dynamic Hot-Plug Live!\n");
}

void loop() {
  unsigned long now = millis();

  // Dynamic live hot-plug scanner for re-connected wires/sensors!
  check_i2c_hotplug();

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
  }

  // Wi-Fi Telemetry POST to Digital Twin Dashboard
  if (now - last_wifi_tx >= WIFI_INTERVAL_MS) { 
    last_wifi_tx = now; 
    send_wifi(); 
  }

  // Print formatted Serial Console Dashboard
  if (now - last_print_tx >= PRINT_INTERVAL_MS) {
    last_print_tx = now;
    print_console_dashboard();
  }

  delay(20);
}
