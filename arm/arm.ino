#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

#define SERVOMIN 120
#define SERVOMAX 600

int angleToPulse(int angle) {
  return map(angle, 0, 270, SERVOMIN, SERVOMAX);
}

void setup() {
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(1000);

  // Servo 1 (index 0) to 180
 pwm.setPWM(0, 0, angleToPulse(0));
 pwm.setPWM(1, 0, angleToPulse(0));
 pwm.setPWM(2, 0, angleToPulse(170)); //30 Min
 pwm.setPWM(3, 0, angleToPulse (140));
 pwm.setPWM(4, 0, angleToPulse(180));
   pwm.setPWM(15, 0, angleToPulse(0));
}

void loop() {
  // Open Claw
//  pwm.setPWM(5, 0, angleToPulse(25));
//  delay(1000);

  // Close Claw
 // pwm.setPWM(5, 0, angleToPulse(100));
//  delay(1000);
}
