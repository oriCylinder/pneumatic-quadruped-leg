#include "Arduino.h"
#include "ESP32Servo.h"
#include "Preferences.h"

#include "PID.h"
#include "DataPollAndParse.h"

//設定値
const uint16_t PVCInterval = 33;                   //PVCの送信周期[ms]
const uint8_t valveTotalNum = 4;                   //バルブ総数(MAX4)
const uint8_t valvePins[4] = { 4, 0, 2, 15 };      //バルブのPWM出力ピン番号
const uint8_t sensorPins[4] = { 26, 27, 14, 12 };  //センサーの入力ピン番号
const float baseGainList[4][3] = {
  { 0.0001, 0.00001, 0.000001 },
  { 0.0001, 0.00001, 0.000001 },
  { 0.0001, 0.00001, 0.000001 },
  { 0.0001, 0.00001, 0.000001 }
};  //ベースのゲインリスト - { pGain, iGain, dGain }

//インスタンスの宣言
Servo valve[valveTotalNum];   //サーボクラスの配列インスタンスを宣言
PID vCommand[valveTotalNum];  //PIDクラスの配列インスタンスを宣言
USBPolling pollData;          //USB通信クラスのインスタンスを宣言
Preferences preferences;      //NVS用のインスタンスを宣言

//戻り値を格納する変数
float commandAry[valveTotalNum] = { 0 };            //バルブへのコマンドを格納する配列
bool commandFlagAry[valveTotalNum] = { 0 };         //コマンドの決定方法(position or command)を格納する配列
uint16_t getValtageAry[valveTotalNum] = { 0 };      //現在の電圧を格納する配列
uint16_t posAry[valveTotalNum][2] = { 0 };          //map後のポジションを格納する配列 - { target, current }
uint16_t capturedValAry[valveTotalNum][2] = { 0 };  //キャプチャー電圧を格納する配列 - { stroke, offset }

//その他変数
uint32_t nowTime;  //現在時刻を格納(PVCの定時送信に使用)
uint32_t preTime;  //前回時間を格納(PVCの定時送信に使用)

//関数のプロトタイプ宣言
void sendDataCGC(uint8_t num);   //CGCデータの送信
void sendDataPVC(uint8_t num);   //PVCデータの送信
void saveData(uint8_t num);      //データをNVSに保存(未実装)
void getGainNVS(uint8_t num);    //ゲインをNVSから読み出し、反映
void getSCapNVS(uint8_t num);    //ストローク側キャプチャー値をNVSから読み出し
void getOCapNVS(uint8_t num);    //オフセット側キャプチャー値をNVSから読み出し
void writeGainNVS(uint8_t num);  //ゲインをNVSへ保存
void writeSCapNVS(uint8_t num);  //ストローク側キャプチャー値をNVSへ保存
void writeOCapNVS(uint8_t num);  //オフセット側キャプチャー値をNVSへ保存

void setup() {
  //各インスタンスの初期設定
  for (int i = 0; i < valveTotalNum; i++) {
    /*---
      サーボクラスのインスタンスを初期設定
      各モータにおけるパルス幅
      SG90 : 500-2400(us)
      MG90 : 1000-2000(us)
      ---*/
    valve[i].attach(valvePins[i], 1000, 2000);  //バルブの仕様を規定
    valve[i].write(90);                         //バルブ初期位置をnullポジション(90deg)に設定

    //PIDクラスのインスタンスを初期設定
    vCommand[i].setBaseGain(baseGainList[i][0], baseGainList[i][1], baseGainList[i][2]);  //ベースゲインを規定
    vCommand[i].clipLimitEnable(true, 90.0, -90.0);                                       //コマンドがサーボの可動域を超えないようクリップ
    vCommand[i].setMinDt(1000);                                                           //最小制御ループ秒数を設定[us]
  }

  //USB通信クラスのインスタンスを初期設定
  pollData.begin(115200);  //通信速度115200bpsで通信開始]

  for (int i = 0; i < valveTotalNum; ++i) {
    getGainNVS(i);  //シリンダーiのゲインを保存値に換装
    getSCapNVS(i);  //ストローク側キャプチャー値を保存値で更新
    getOCapNVS(i);  //オフセット側キャプチャー値を保存値で更新
  }

  preTime = millis();  //時間を初期化

  // //キャプチャー未実装のため仮の初期値を設定
  // capturedValAry[0][0] = { 2000 };
  // capturedValAry[0][1] = { 200 };
  // capturedValAry[1][0] = { 2000 };
  // capturedValAry[1][1] = { 200 };
  // capturedValAry[2][0] = { 2000 };
  // capturedValAry[2][1] = { 200 };
  // capturedValAry[3][0] = { 2000 };
  // capturedValAry[3][1] = { 200 };
}

void loop() {
  nowTime = millis();  //定時送信用の時間を取得

  //一定時間たったらPVCの送信処理
  if (nowTime - preTime >= PVCInterval) {
    //バルブの個数だけ繰り返す
    for (int i = 0; i < valveTotalNum; i++) {
      sendDataPVC(i);  //PVC送信関数
    }
    preTime = nowTime;  //前回時間を更新
  }

  //受信データがあるか確認(データがあればtrue、なければfalseが返ってくる)
  if (pollData.poll()) {
    const ParsedDataStruct& parsedData = pollData.getParsedData();  //パースされたデータを格納する構造体(戻り値はconst参照)
    uint16_t dataAry[8] = {
      parsedData.field1,
      parsedData.field2,
      parsedData.field3,
      parsedData.field4,
      parsedData.field5,
      parsedData.field6,
      parsedData.field7,
      parsedData.field8,
    };  //データを配列に変換

    //フォーマット番号ごとに処理を決定
    switch (parsedData.format) {
      //COMのとき
      case 63:
        for (int i = 0; i < valveTotalNum; i++) {  //バルブの個数だけ繰り返す

          if (dataAry[i] == 1) {                                  //もしシリンダーiのデータがcommand指示なら
            commandFlagAry[i] = 1;                                //コマンドフラグをcommandにする
            commandAry[i] = float(dataAry[i + 4]) / 10.0 - 90.0;  //コマンドを送られてきたデータに設定(0-1800で受信するため10で割る)

          } else if (dataAry[i] == 0) {            //もしシリンダーiのデータがposition指示なら
            commandFlagAry[i] = 0;                 //コマンドフラグをpositionにする
            posAry[i][0] = dataAry[i + 4];  //ポジション配列のtargetに送られてきたデータを格納
          }
        }
        break;

      //REQのとき
      case 1:
        for (int i = 0; i < valveTotalNum; i++) {  //バルブの個数だけ繰り返す
          if (dataAry[i] == 1) {                   //もしシリンダーiのCGC要求なら
            sendDataCGC(i);                        //シリンダーiのCGC送信関数を実行
          }
        }

        for (int i = 0; i < valveTotalNum; i++) {  //バルブの個数だけ繰り返す
          if (dataAry[i + 4] == 1) {               //もしシリンダーiのセーブ要求なら
            saveData(i);                           //シリンダーiのデータセーブ関数を実行
            sendDataCGC(i);                        //シリンダーiのCGC送信関数を実行
          }
        }
        break;

      //LGC1のとき
      case 10:
        vCommand[0].setGain(static_cast<uint16_t>(dataAry[0]),
                            static_cast<uint16_t>(dataAry[1]),
                            static_cast<uint16_t>(dataAry[2]));  //シリンダー0のゲインを受信値に換装

        sendDataCGC(0);  //シリンダー0のCGC送信関数を実行
        break;

      case 20:  //LGC2のとき
        vCommand[1].setGain(static_cast<uint16_t>(dataAry[0]),
                            static_cast<uint16_t>(dataAry[1]),
                            static_cast<uint16_t>(dataAry[2]));  //シリンダー1のゲインを受信値に換装

        sendDataCGC(1);  //シリンダー1のCGC送信関数を実行
        break;

      //LGC3のとき
      case 30:
        vCommand[2].setGain(static_cast<uint16_t>(dataAry[0]),
                            static_cast<uint16_t>(dataAry[1]),
                            static_cast<uint16_t>(dataAry[2]));  //シリンダー2のゲインを受信値に換装

        sendDataCGC(2);  //シリンダー2のCGC送信関数を実行
        break;

      //LGC4のとき
      case 40:
        vCommand[3].setGain(static_cast<uint16_t>(dataAry[0]),
                            static_cast<uint16_t>(dataAry[1]),
                            static_cast<uint16_t>(dataAry[2]));  //シリンダー3のゲインを受信値に換装

        sendDataCGC(3);  //シリンダー3のCGC送信関数を実行
        break;

      //CAPのとき
      case 50:
        if ((dataAry[4] + dataAry[5] != 2) && (dataAry[0] + dataAry[1] + dataAry[2] + dataAry[3] < 2)) {  //キャプチャー要求のダブりがないか検査
          for (int i = 0; i < valveTotalNum; i++) {                                                       //バルブの個数だけ繰り返す
            if (dataAry[i] == 1) {                                                                        //もしシリンダーiの要求なら
              if (dataAry[4] == 1) {                                                                      //もしストローク側の要求なら
                capturedValAry[i][0] = analogRead(sensorPins[i]);                                         //シリンダーiのストローク側キャプチャー値を更新
              } else if (dataAry[5] == 1) {                                                               //もしオフセット側の要求なら
                capturedValAry[i][1] = analogRead(sensorPins[i]);                                         //シリンダーiのオフセット側キャプチャー値を更新
              }
              sendDataCGC(i);  //シリンダーiのCGC送信関数を実行
            }
          }
        }
        break;

      default:                         //それ以外の時(受信エラーまたは想定外のフォーマットを受信)
        pollData.clearSerialBuffer();  //シリアルバッファがずれてる可能性があるため全消去する
        break;
    }
  } else {
  }

  //PID処理
  for (int i = 0; i < valveTotalNum; i++) {                                                //バルブの個数だけ繰り返す
    getValtageAry[i] = analogRead(sensorPins[i]);                                          //センサーの値を取得
    int buf = map(getValtageAry[i],  capturedValAry[i][1], capturedValAry[i][0], 0, 4095); //取得値をキャプチャー値でMapping
    if (buf < 0) {                                                                         //Mappingされた値が0よ小さければ
      buf = 0;                                                                             //0に修正
    } else if (buf > 4095) {                                                               //Mappingされた値が4095より大きければ
      buf = 4095;                                                                          //4095に修正
    }
    posAry[i][1] = buf;  //Mappingされた値を反映

    if (commandFlagAry[i]) {                                                //もしコマンドフラグがcommandなら
      valve[i].write(commandAry[i] + 90.0);                                   //バルブへcommandの値をそのまま送信
      vCommand[i].timeReset();                                              //念のためPID処理の時間をリセットしておく
    } else {                                                                //もしコマンドフラグがpositionなら
      commandAry[i] = vCommand[i].calcCommand(posAry[i][0], posAry[i][1]);  //PID関数を実行しcommandを取得
      valve[i].write(commandAry[i] + 90.0);                                   //バルブへcommandを送信(戻り値が-90から90なので0から180に再設定)
    }
  }
}

void sendDataCGC(uint8_t num) {
  const gainStruct& gain = vCommand[num].getGain();  //ゲインを格納する構造体
  const uint64_t& binaryData = pollData.dataCoupling(static_cast<uint8_t>(10 * (num + 1) + 1),
                               static_cast<uint16_t>(gain.pGain),
                               static_cast<uint16_t>(gain.iGain),
                               static_cast<uint16_t>(gain.dGain),
                               capturedValAry[num][0],
                               capturedValAry[num][1]);
  pollData.sendData(binaryData);
}

void sendDataPVC(uint8_t num) {
  const uint64_t& binaryData = pollData.dataCoupling(static_cast<uint8_t>(num + 5),
                               posAry[num][1],
                               getValtageAry[num],
                               static_cast<uint16_t>((commandAry[num] + 90.0) * 10.0),
                               0,
                               0);
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
  preferences.putUShort(("oCapCal" + String(num)).c_str(), capturedValAry[num][1]);
  preferences.end();

  getOCapNVS(num);
}
