#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

#define SERVOMIN 120
#define SERVOMAX 600

// Only this channel is touched - every other channel is left alone
#define FIRST_MOTOR_CHANNEL 0
#define CENTER_ANGLE 135

int angleToPulse(int angle) {
  return map(angle, 0, 270, SERVOMIN, SERVOMAX);
}

void setup() {
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(1000);

  pwm.setPWM(FIRST_MOTOR_CHANNEL, 0, angleToPulse(CENTER_ANGLE));
}

void loop() {
}
