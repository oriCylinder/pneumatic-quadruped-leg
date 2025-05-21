#include "Arduino.h"
#include "math.h"

#include "PID.h"

PID::PID(void) {
  _preTime = micros();
  _clipLimit.enable = false;
  setBaseGain(0.0, 0.0, 0.0);
  setGain(0.0, 0.0, 0.0);
  for (int i = 0; i < 3; i++) {
    _err[i] = 0;
  }
}

void PID::setBaseGain(const float pBaseGain, const float iBaseGain, const float dBaseGain) {
  _gains.pBaseGain = pBaseGain;
  _gains.iBaseGain = iBaseGain;
  _gains.dBaseGain = dBaseGain;
}

void PID::setGain(const uint8_t pGain, const uint8_t iGain, const uint8_t dGain) {
  _gains.pGain = pGain;
  _gains.iGain = iGain;
  _gains.dGain = dGain;
  _gains.pCalcGain = _gains.pBaseGain * float(_gains.pGain * _gains.pGain) / 64.0;
  _gains.iCalcGain = _gains.iBaseGain * float(_gains.iGain * _gains.iGain) / 64.0;
  _gains.dCalcGain = _gains.dBaseGain * float(_gains.dGain * _gains.dGain) / 64.0;
}

void PID::setMinDt(const uint16_t dt) {
  _minDt = dt;
}

const gainStruct& PID::getGain(void) const {
  return _gains;
}

float PID::calcCommand(const uint16_t targetPosition, const uint16_t currentPosition) {
  _nowTime = micros();
  _dt = double(_nowTime - _preTime);
  if (_dt >= _minDt) {
    _dt = _dt / 1000000.0;
    _preTime = _nowTime;
    for (int i = 0; i < 2; i++) {
      _err[i + 1] = _err[i];
    }
    _err[0] = targetPosition - currentPosition;
    _posErr = double(_err[0] - _err[1]);
    _velErr = double(_err[0]) * _dt;
    _accErr = double(_err[0] - _err[1] - _err[1] + _err[2]) / _dt;
    _command = _command + float(_gains.pCalcGain * _posErr + _gains.iCalcGain * _velErr + _gains.dCalcGain * _accErr);

    if (_clipLimit.enable) {
      if (_command > _clipLimit.high) {
        _retCommand = _clipLimit.high;
      } else if (_command < _clipLimit.low) {
        _retCommand = _clipLimit.low;
      } else {
        _retCommand = _command;
      }
    } else {
      _retCommand = _command;
    }
  }
  return _retCommand;
}

void PID::clipLimitEnable(const bool enable, const float highSideLimit, const float lowSideLimit) {
  _clipLimit.enable = enable;
  _clipLimit.high = highSideLimit;
  _clipLimit.low = lowSideLimit;
}

void PID::clipLimitDisable(const bool enable) {
  _clipLimit.enable = enable;
}

void PID::timeReset(void) {
  _preTime = micros();
}
