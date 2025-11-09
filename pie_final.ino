#include <EEPROM.h>

const int motorPinsR[3] = {2, 3, 4}; 
const int motorPinsG[3] = {5, 6, 7}; 
const int motorPinsO[3] = {8, 9, 10}; 
const int motorPinsY[3] = {2, 3, 4}; 

const int microStep = 200;  
const int stepDelay = 175;  

byte boardID;
String command[1000];
int count = 0;

void setup() {
  Serial.begin(9600);
  boardID = EEPROM.read(0);

  for (int i = 0; i < 3; i++) {
    pinMode(motorPinsR[i], OUTPUT);
    pinMode(motorPinsG[i], OUTPUT);
    pinMode(motorPinsO[i], OUTPUT);
    pinMode(motorPinsY[i], OUTPUT);    
  }

}

void runMotor(char motor) {
  int pins[3];

  if (motor == 'R') {
    for (int i = 0; i < 3; i++) pins[i] = motorPinsR[i];
  } else if (motor == 'G') {
    for (int i = 0; i < 3; i++) pins[i] = motorPinsG[i];
  } else if (motor == 'O') {
    for (int i = 0; i < 3; i++) pins[i] = motorPinsO[i];
  } else if (motor == 'Y') {
    for (int i = 0; i < 3; i++) pins[i] = motorPinsY[i];
  } else {
    return;
  }

  int enPin = pins[0];
  int dirPin = pins[1];
  int stepPin = pins[2];
  digitalWrite(enPin, LOW);
  digitalWrite(dirPin, HIGH);

  for (int i = 0; i < microStep; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);
  }

  digitalWrite(enPin, HIGH);
  delay(150);
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.equals("END")){
      for (int i = 0; i < count; i++){
        String oneLine = command[i];
        int commaIndex = oneLine.indexOf(',');
        if (commaIndex > 0) {
          int receivedID = oneLine.substring(0, commaIndex).toInt();
          char motor = oneLine.charAt(commaIndex + 1);

          if (receivedID == boardID) {
            runMotor(motor);
          }
        }
      }
      count = 0;
    } else {
      command[count++] = line;
    }
  }
}