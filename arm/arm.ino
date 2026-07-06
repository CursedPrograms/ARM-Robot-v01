#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

#define SERVOMIN 120
#define SERVOMAX 600

// Must match the baud rate used in run.py (--baud, default 115200)
#define BAUD_RATE 115200

int angleToPulse(int angle) {
  return map(angle, 0, 270, SERVOMIN, SERVOMAX);
}

void setup() {
  Serial.begin(BAUD_RATE);

  pwm.begin();
  pwm.setPWMFreq(50);
  delay(1000);

  // Startup position (same as your original sketch)
  pwm.setPWM(0, 0, angleToPulse(0));
  pwm.setPWM(1, 0, angleToPulse(0));
  pwm.setPWM(2, 0, angleToPulse(170)); // 30 Min
  pwm.setPWM(3, 0, angleToPulse(140));
  pwm.setPWM(4, 0, angleToPulse(180));
  pwm.setPWM(15, 0, angleToPulse(0));
}

void loop() {
  // run.py sends lines like: "0:135,1:90,2:170,5:25\n"
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      applyCommandLine(line);
    }
  }
}

void applyCommandLine(String line) {
  int start = 0;
  while (start < (int)line.length()) {
    int comma = line.indexOf(',', start);
    String pair = (comma == -1) ? line.substring(start) : line.substring(start, comma);

    int colon = pair.indexOf(':');
    if (colon != -1) {
      int channel = pair.substring(0, colon).toInt();
      int angle = pair.substring(colon + 1).toInt();
      angle = constrain(angle, 0, 270);

      if (channel >= 0 && channel <= 15) {
        pwm.setPWM(channel, 0, angleToPulse(angle));
      }
    }

    if (comma == -1) break;
    start = comma + 1;
  }
}
