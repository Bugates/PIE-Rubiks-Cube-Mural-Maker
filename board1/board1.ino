#include <EEPROM.h>

const byte motorPins[4][3] = {
  {4, 3, 2},   // F
  {7, 6, 5},   // R
  {8, 9, 10},  // B
  {11, 12, 13},// L
};


const int microStep = 200;  
const int stepDelay = 300;  

byte boardID;
bool terminated = false;

void setup() {
  Serial.begin(9600);
  boardID = EEPROM.read(0);

  for (int m = 0; m < 4; m++) {
    for (int i = 0; i < 3; i++) {
      pinMode(motorPins[m][i], OUTPUT);
    }
  }
}

void runMotor(int motorID, int direction) {
  int enPin   = motorPins[motorID][0];
  int dirPin  = motorPins[motorID][1];
  int stepPin = motorPins[motorID][2];

  digitalWrite(enPin, LOW);
  digitalWrite(dirPin, (direction == 1) ? LOW : HIGH);

  for (int i = 0; i < microStep; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);
  }

  digitalWrite(enPin, HIGH);
  delay(stepDelay);
}

void loop() {

  if (Serial.available()) {
    int code = Serial.read(); 
    int receivedBoard = code / 100;       
    int motorID       = (code / 10) % 10;
    int direction     = code % 10;

    if (receivedBoard == boardID) {
      runMotor(motorID-1, direction);
    }

    Serial.println("DONE");
  }
}
