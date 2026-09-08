/*
 * ENVIRON-X — EEPROM Module Flasher & Writer
 * 
 * Hardware: Arduino Uno / Nano / ESP32 + 24C02 / 24C32 I2C EEPROM (Address 0x50 - 0x57)
 * 
 * Pin Mapping:
 * - Arduino Uno / Nano : SDA = A4, SCL = A5
 * - ESP32              : SDA = 21, SCL = 22
 */

#include <Wire.h>

uint8_t target_eeprom_addr = 0x50; // Default I2C address

struct __attribute__((packed)) ModuleEEPROMHeader {
  uint16_t magic;          // 0x4558 ('EX')
  uint8_t  sensor_type_id; // 1=BMP280, 2=MQ135, 3=GP2Y, 4=WATER, 5=MPU6050, 6=SOIL
  char     sensor_name[16];// Human readable string
  float    calib_min;      // Minimum range
  float    calib_max;      // Maximum range
  uint32_t checksum;       // Simple checksum
};

void writeEEPROMHeader(uint8_t i2c_addr, const ModuleEEPROMHeader& header) {
  const uint8_t* p = (const uint8_t*)&header;
  size_t len = sizeof(ModuleEEPROMHeader);

  Serial.print(F("[EEPROM FLASH] Writing "));
  Serial.print(len);
  Serial.print(F(" bytes to EEPROM at 0x"));
  Serial.println(i2c_addr, HEX);

  // Check if device responds
  Wire.beginTransmission(i2c_addr);
  uint8_t test_err = Wire.endTransmission();
  if (test_err != 0) {
    Serial.print(F("[ERROR] I2C Device 0x"));
    Serial.print(i2c_addr, HEX);
    Serial.print(F(" failed to respond! (Error Code: "));
    Serial.print(test_err);
    Serial.println(F(")"));
    Serial.println(F("Please verify wiring: SDA -> Arduino SDA Pin, SCL -> Arduino SCL Pin, VCC -> 5V/3.3V, GND -> GND"));
    return;
  }

  // Attempt 1: Standard 1-byte addressing (24C02 / 24C04 / 24C08 / 24C16)
  for (size_t i = 0; i < len; i++) {
    Wire.beginTransmission(i2c_addr);
    Wire.write((uint8_t)i); // 1-byte memory address
    Wire.write(p[i]);       // Byte data
    Wire.endTransmission();
    delay(10); // EEPROM write cycle delay (5-10ms)
  }

  // Quick verify
  ModuleEEPROMHeader test_read = readEEPROMHeader(i2c_addr);
  if (test_read.magic != 0x4558) {
    // Attempt 2: 2-byte addressing (24C32 / 24C64 / 24C256)
    Serial.println(F("[EEPROM FLASH] 1-Byte address missed magic marker, trying 2-byte address write (24C32/64)..."));
    for (size_t i = 0; i < len; i++) {
      Wire.beginTransmission(i2c_addr);
      Wire.write((uint8_t)0);        // Address High Byte
      Wire.write((uint8_t)i);        // Address Low Byte
      Wire.write(p[i]);              // Byte data
      Wire.endTransmission();
      delay(10);
    }
  }

  Serial.println(F("[EEPROM FLASH] Write Cycle Complete! Verifying..."));
}

ModuleEEPROMHeader readEEPROMHeader(uint8_t i2c_addr) {
  ModuleEEPROMHeader header;
  memset(&header, 0, sizeof(ModuleEEPROMHeader));
  uint8_t* p = (uint8_t*)&header;
  size_t len = sizeof(ModuleEEPROMHeader);

  Wire.beginTransmission(i2c_addr);
  uint8_t err = Wire.endTransmission();
  if (err != 0) {
    Serial.print(F("[ERROR] EEPROM at 0x"));
    Serial.print(i2c_addr, HEX);
    Serial.print(F(" not responding on I2C bus! (Error Code: "));
    Serial.print(err);
    Serial.println(F(")"));
    Serial.println(F("Check wiring: SDA -> Arduino SDA Pin, SCL -> Arduino SCL Pin, VCC, GND"));
    return header;
  }

  // Try 1-byte address first (24C02 standard)
  Wire.beginTransmission(i2c_addr);
  Wire.write((uint8_t)0);
  Wire.endTransmission();

  for (size_t i = 0; i < len; i++) {
    if (Wire.requestFrom(i2c_addr, (uint8_t)1) == 1) {
      p[i] = Wire.read();
    } else {
      break;
    }
  }

  // If 1-byte address didn't yield magic marker 0x4558, try 2-byte addressing (24C32/64)
  if (header.magic != 0x4558) {
    Wire.beginTransmission(i2c_addr);
    Wire.write(0);
    Wire.write(0);
    if (Wire.endTransmission() == 0) {
      for (size_t i = 0; i < len; i++) {
        if (Wire.requestFrom(i2c_addr, (uint8_t)1) == 1) {
          p[i] = Wire.read();
        } else {
          break;
        }
      }
    }
  }

  return header;
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000);

#if defined(ESP32)
  Wire.begin(21, 22);
#else
  Wire.begin();  // Standard Arduino Wire SDA & SCL
  digitalWrite(SDA, HIGH); // Enable internal pullup on SDA
  digitalWrite(SCL, HIGH); // Enable internal pullup on SCL
  Wire.setWireTimeout(25000, true); // Enable 25ms hardware timeout to prevent TWI hangs
#endif

  Serial.println(F("\n=============================================="));
  Serial.println(F("   ENVIRON-X — Plug & Play EEPROM Flasher     "));
  Serial.println(F("=============================================="));

  target_eeprom_addr = 0x50; // Standard I2C address for 24C02/32 EEPROM
  Serial.print(F("[READY] Target EEPROM I2C Address set to: 0x"));
  Serial.println(target_eeprom_addr, HEX);

  // Print Menu
  Serial.println(F("\nSelect Action / Sensor Type for EEPROM:"));
  Serial.println(F(" 1. BME280 Temp / Humidity / Barometric Pressure"));
  Serial.println(F(" 2. MQ135 Air Quality / Hazardous Gas Sensor"));
  Serial.println(F(" 3. GP2Y1010 Optical Smoke & Dust Particle Sensor"));
  Serial.println(F(" 4. Water Level Depth Sensor"));
  Serial.println(F(" 5. MPU6050 Vibration & Slope Tilt Sensor"));
  Serial.println(F(" 6. Resistive Soil Moisture Sensor"));
  Serial.println(F(" 7. READ & DUMP Current EEPROM Memory"));
  Serial.println(F(" 8. Scan I2C Bus"));
  Serial.println(F("Enter choice (1-8) in Serial Monitor:"));
}

void loop() {
  if (Serial.available()) {
    char ch = Serial.read();
    if (ch == '7' || ch == 'r') {
      Serial.println(F("\n[EEPROM READ] Reading current memory from 0x50..."));
      ModuleEEPROMHeader readback = readEEPROMHeader(target_eeprom_addr);
      Serial.println(F("----------------------------------------------"));
      Serial.print(F("  Magic Marker : 0x")); Serial.println(readback.magic, HEX);
      if (readback.magic == 0x4558) {
        Serial.print(F("  Header Status: VALID ('EX')\n"));
        Serial.print(F("  Sensor Name  : ")); Serial.println(readback.sensor_name);
        Serial.print(F("  Type ID      : ")); Serial.println(readback.sensor_type_id);
        Serial.print(F("  Calib Range  : ")); Serial.print(readback.calib_min); Serial.print(F(" to ")); Serial.println(readback.calib_max);
      } else {
        Serial.println(F("  Header Status: UNFORMATTED / EMPTY (Magic != 0x4558)"));
      }
      Serial.println(F("----------------------------------------------"));
    } else if (ch >= '1' && ch <= '6') {
      int choice = ch - '0';
      ModuleEEPROMHeader header;
      header.magic = 0x4558; // 'EX'
      header.sensor_type_id = choice;
      memset(header.sensor_name, 0, sizeof(header.sensor_name));

      switch (choice) {
        case 1:
          strncpy(header.sensor_name, "BME280_TEMP_PRES", 15);
          header.calib_min = -40.0f; header.calib_max = 85.0f;
          break;
        case 2:
          strncpy(header.sensor_name, "MQ135_GAS_SENSOR", 15);
          header.calib_min = 10.0f; header.calib_max = 1000.0f;
          break;
        case 3:
          strncpy(header.sensor_name, "GP2Y_DUST_SMOKE", 15);
          header.calib_min = 0.0f; header.calib_max = 500.0f;
          break;
        case 4:
          strncpy(header.sensor_name, "WATER_LEVEL_CM", 15);
          header.calib_min = 0.0f; header.calib_max = 100.0f;
          break;
        case 5:
          strncpy(header.sensor_name, "MPU6050_VIB_TILT", 15);
          header.calib_min = -180.0f; header.calib_max = 180.0f;
          break;
        case 6:
          strncpy(header.sensor_name, "SOIL_RESISTIVE", 15);
          header.calib_min = 0.0f; header.calib_max = 100.0f;
          break;
      }

      writeEEPROMHeader(target_eeprom_addr, header);

      // Verify Readback
      ModuleEEPROMHeader verify = readEEPROMHeader(target_eeprom_addr);
      if (verify.magic == 0x4558) {
        Serial.println(F("----------------------------------------------"));
        Serial.println(F("[SUCCESS] EEPROM Flash Verified Successfully!"));
        Serial.print(F("  Sensor Name : ")); Serial.println(verify.sensor_name);
        Serial.print(F("  Type ID     : ")); Serial.println(verify.sensor_type_id);
        Serial.print(F("  Calib Min   : ")); Serial.println(verify.calib_min);
        Serial.print(F("  Calib Max   : ")); Serial.println(verify.calib_max);
        Serial.println(F("----------------------------------------------"));
        Serial.println(F("Module is now ready for Plug-and-Play auto-discovery on any ESP32 port!"));
      } else {
        Serial.println(F("[ERROR] Verification failed! Magic header mismatch."));
      }
    } else if (ch == '8' || ch == 's') {
      Serial.println(F("\n[I2C BUS SCANNER] Probing addresses 0x08 to 0x77..."));
      uint8_t count = 0;
      for (uint8_t addr = 0x08; addr <= 0x77; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
          Serial.print(F("  -> [FOUND] Active I2C Device at address: 0x"));
          if (addr < 16) Serial.print(F("0"));
          Serial.println(addr, HEX);
          if (addr >= 0x50 && addr <= 0x57) {
            target_eeprom_addr = addr;
          }
          count++;
        }
      }
      if (count == 0) {
        Serial.println(F("  -> [NONE] No I2C devices responded on bus."));
      } else {
        Serial.print(F("  -> Target EEPROM address set to: 0x"));
        Serial.println(target_eeprom_addr, HEX);
      }
    }
  }
  delay(100);
}
