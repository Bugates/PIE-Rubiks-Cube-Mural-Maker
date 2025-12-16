#include <Wire.h>
#include <Adafruit_MotorShield.h>
#include "utility/Adafruit_MS_PWMServoDriver.h"
#include <EEPROM.h>

Adafruit_MotorShield AFMS = Adafruit_MotorShield(); 
Adafruit_DCMotor *myMotor = AFMS.getMotor(1);
byte boardID;
bool terminated = false;

void setup() {
  Serial.begin(9600);
  boardID = EEPROM.read(0);
  AFMS.begin();
  myMotor->setSpeed(100);
}

void loop() {
  if (Serial.available()) {
    int code = Serial.parseInt(); 
    int receivedBoard = code / 100;       
    int motorID       = (code / 10) % 10;
    int direction     = code % 10;

    if (receivedBoard == boardID) {
      myMotor->run(FORWARD);
      delay(2000);
      myMotor->run(RELEASE);
    }
    Serial.println("DONE");
  }
  
}
