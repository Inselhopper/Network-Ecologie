#include <Servo.h>

Servo mouthServo;
String input = "";

void setup() {
  Serial.begin(115200);
  mouthServo.attach(9);
  mouthServo.write(90);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      int value = input.toInt();
      value = constrain(value, 0, 180);
      mouthServo.write(value);
      input = "";
    } else if (isDigit(c)) {
      input += c;
    }
  }
}