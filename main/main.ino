#include "Arduino.h"
#include "ESP32Servo.h"
#include "Preferences.h"
#include "PID.h"
#include "DataPollAndParse.h"

// LED関連ピン
const uint8_t LED_RX = 16;
const uint8_t LED_TX = 17;
const uint8_t LED_ERR = 13;

// LED点灯状態保持
bool ledRxOn = false;
bool ledTxOn = false;
bool ledErrOn = false;
uint32_t ledRxTimer = 0;
uint32_t ledTxTimer = 0;
uint32_t ledErrTimer = 0;

// 設定値
const uint16_t PVCInterval = 33;
const uint8_t valveTotalNum = 4;
const uint8_t valvePins[4] = {4, 0, 2, 15};
const uint8_t sensorPins[4] = {26, 27, 14, 12};
const float baseGainList[4][3] = {
  {0.0001, 0.00001, 0.000001},
  {0.0001, 0.00001, 0.000001},
  {0.0001, 0.00001, 0.000001},
  {0.0001, 0.00001, 0.000001}
};

// インスタンス
Servo valve[valveTotalNum];
PID vCommand[valveTotalNum];
USBPolling pollData;
Preferences preferences;

// データ保持
float commandAry[valveTotalNum] = {0};
bool commandFlagAry[valveTotalNum] = {0};
uint16_t getValtageAry[valveTotalNum] = {0};
uint16_t posAry[valveTotalNum][2] = {0};
uint16_t capturedValAry[valveTotalNum][2] = {0};

// タイマー
uint32_t nowTime;
uint32_t preTime;

// プロトタイプ宣言
void sendDataPVC(uint8_t num);
void sendDataCGC(uint8_t num);
void saveData(uint8_t num);
void getGainNVS(uint8_t num);
void getSCapNVS(uint8_t num);
void getOCapNVS(uint8_t num);
void writeGainNVS(uint8_t num);
void writeSCapNVS(uint8_t num);
void writeOCapNVS(uint8_t num);
void handleLEDs();

void setup() {
  // LEDピン出力設定
  pinMode(LED_RX, OUTPUT);
  pinMode(LED_TX, OUTPUT);
  pinMode(LED_ERR, OUTPUT);
  digitalWrite(LED_RX, LOW);
  digitalWrite(LED_TX, LOW);
  digitalWrite(LED_ERR, LOW);

  for (int i = 0; i < valveTotalNum; i++) {
    valve[i].attach(valvePins[i], 1000, 2000);
    valve[i].write(90);
    vCommand[i].setBaseGain(baseGainList[i][0], baseGainList[i][1], baseGainList[i][2]);
    vCommand[i].clipLimitEnable(true, 90.0, -90.0);
    vCommand[i].setMinDt(1000);
  }

  pollData.begin(115200);

  for (int i = 0; i < valveTotalNum; ++i) {
    getGainNVS(i);
    getSCapNVS(i);
    getOCapNVS(i);
  }

  preTime = millis();
}

void loop() {
  nowTime = millis();

  if (nowTime - preTime >= PVCInterval) {
    for (int i = 0; i < valveTotalNum; i++) {
      sendDataPVC(i);
      digitalWrite(LED_TX, HIGH); ledTxOn = true; ledTxTimer = millis();
    }
    preTime = nowTime;
  }

  if (pollData.poll()) {
    digitalWrite(LED_RX, HIGH); ledRxOn = true; ledRxTimer = millis();
    const ParsedDataStruct& parsedData = pollData.getParsedData();
    uint16_t dataAry[8] = {
      parsedData.field1, parsedData.field2, parsedData.field3, parsedData.field4,
      parsedData.field5, parsedData.field6, parsedData.field7, parsedData.field8,
    };

    switch (parsedData.format) {
      case 63:
        for (int i = 0; i < valveTotalNum; i++) {
          if (dataAry[i] == 1) {
            commandFlagAry[i] = 1;
            commandAry[i] = float(dataAry[i + 4]) / 10.0 - 90.0;
          } else if (dataAry[i] == 0) {
            commandFlagAry[i] = 0;
            posAry[i][0] = dataAry[i + 4];
          }
        }
        break;

      case 1:
        for (int i = 0; i < valveTotalNum; i++) {
          if (dataAry[i] == 1) sendDataCGC(i);
        }
        for (int i = 0; i < valveTotalNum; i++) {
          if (dataAry[i + 4] == 1) {
            saveData(i);
            sendDataCGC(i);
          }
        }
        break;

      case 10: case 20: case 30: case 40:
        {
          uint8_t idx = parsedData.format / 10 - 1;
          vCommand[idx].setGain(dataAry[0], dataAry[1], dataAry[2]);
          sendDataCGC(idx);
        }
        break;

      case 50:
        if ((dataAry[4] + dataAry[5] != 2) && (dataAry[0] + dataAry[1] + dataAry[2] + dataAry[3] < 2)) {
          for (int i = 0; i < valveTotalNum; i++) {
            if (dataAry[i] == 1) {
              if (dataAry[4] == 1) {
                capturedValAry[i][0] = analogRead(sensorPins[i]);
              } else if (dataAry[5] == 1) {
                capturedValAry[i][1] = analogRead(sensorPins[i]);
              }
              sendDataCGC(i);
            }
          }
        }
        break;

      default:
        pollData.clearSerialBuffer();
        digitalWrite(LED_ERR, HIGH); ledErrOn = true; ledErrTimer = millis();
        break;
    }
  }

  for (int i = 0; i < valveTotalNum; i++) {
    getValtageAry[i] = analogRead(sensorPins[i]);
    int buf = map(getValtageAry[i], capturedValAry[i][1], capturedValAry[i][0], 0, 4095);
    buf = constrain(buf, 0, 4095);
    posAry[i][1] = buf;

    if (commandFlagAry[i]) {
      valve[i].write(commandAry[i] + 90.0);
      vCommand[i].timeReset();
    } else {
      commandAry[i] = vCommand[i].calcCommand(posAry[i][0], posAry[i][1]);
      valve[i].write(commandAry[i] + 90.0);
    }
  }

  handleLEDs();  // LEDの非同期制御
}

void handleLEDs() {
  if (ledRxOn && millis() - ledRxTimer >= 200) {
    digitalWrite(LED_RX, LOW);
    ledRxOn = false;
  }
  if (ledTxOn && millis() - ledTxTimer >= 200) {
    digitalWrite(LED_TX, LOW);
    ledTxOn = false;
  }
  if (ledErrOn && millis() - ledErrTimer >= 200) {
    digitalWrite(LED_ERR, LOW);
    ledErrOn = false;
  }
}

void sendDataPVC(uint8_t num) {
  uint64_t binaryData = pollData.dataCoupling(static_cast<uint8_t>(num + 5),
                             posAry[num][1],
                             getValtageAry[num],
                             static_cast<uint16_t>((commandAry[num] + 90.0) * 10.0),
                             0, 0);
  pollData.sendData(binaryData);
}

void sendDataCGC(uint8_t num) {
  const gainStruct& gain = vCommand[num].getGain();
  uint64_t binaryData = pollData.dataCoupling(static_cast<uint8_t>(10 * (num + 1) + 1),
                             gain.pGain,
                             gain.iGain,
                             gain.dGain,
                             capturedValAry[num][0],
                             capturedValAry[num][1]);
  pollData.sendData(binaryData);
}

void saveData(uint8_t num) {
  writeGainNVS(num);
  writeSCapNVS(num);
  writeOCapNVS(num);
}

void getGainNVS(uint8_t num) {
  preferences.begin("myNVS", true);
  vCommand[num].setGain(preferences.getUChar(("pGain" + String(num)).c_str(), 0),
                        preferences.getUChar(("iGain" + String(num)).c_str(), 0),
                        preferences.getUChar(("dGain" + String(num)).c_str(), 0));
  preferences.end();
}

void getSCapNVS(uint8_t num) {
  preferences.begin("myNVS", true);
  capturedValAry[num][0] = preferences.getUShort(("sCapCal" + String(num)).c_str(), 2000);
  preferences.end();
}

void getOCapNVS(uint8_t num) {
  preferences.begin("myNVS", true);
  capturedValAry[num][1] = preferences.getUShort(("oCapVal" + String(num)).c_str(), 200);
  preferences.end();
}

void writeGainNVS(uint8_t num) {
  const gainStruct& gain = vCommand[num].getGain();
  preferences.begin("myNVS", false);
  preferences.putUChar(("pGain" + String(num)).c_str(), gain.pGain);
  preferences.putUChar(("iGain" + String(num)).c_str(), gain.iGain);
  preferences.putUChar(("dGain" + String(num)).c_str(), gain.dGain);
  preferences.end();
  getGainNVS(num);
}

void writeSCapNVS(uint8_t num) {
  preferences.begin("myNVS", false);
  preferences.putUShort(("sCapCal" + String(num)).c_str(), capturedValAry[num][0]);
  preferences.end();
  getSCapNVS(num);
}

void writeOCapNVS(uint8_t num) {
  preferences.begin("myNVS", false);
  preferences.putUShort(("oCapVal" + String(num)).c_str(), capturedValAry[num][1]);
  preferences.end();
  getOCapNVS(num);
}
