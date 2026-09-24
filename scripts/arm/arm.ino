#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x40);

#define SERVOMIN 120
#define SERVOMAX 600
#define NUM_CHANNELS 16

// Must match the baud rate used in controller.py (--baud, default 115200)
#define BAUD_RATE 115200

// Motion smoothing: instead of snapping straight to a newly-commanded angle,
// each channel eases toward it a little every UPDATE_INTERVAL_MS, closing
// LERP_FACTOR of the remaining distance each step. Higher LERP_FACTOR/lower
// UPDATE_INTERVAL_MS = snappier; lower/higher = smoother but slower to arrive.
#define LERP_FACTOR 0.15
#define UPDATE_INTERVAL_MS 15

// Rest pose for channels 0-5 (motors 1-6). The arm starts here, and eases back
// here when the PC stops sending. Keep in sync with config.json's "rest" values.
#define NUM_MOTORS 6
const int REST_ANGLE[NUM_MOTORS] = {135, 55, 100, 230, 135, 40};

// The controllers resend their command line at least every 0.5 s while
// running. No command for this long means the PC program closed or crashed.
#define LINK_TIMEOUT_MS 2000

float currentAngle[NUM_CHANNELS];
float targetAngle[NUM_CHANNELS];
bool channelActive[NUM_CHANNELS];
unsigned long lastUpdate = 0;
unsigned long lastCommand = 0;
bool linked = false; // true while a controller is sending commands

int angleToPulse(int angle) {
  return map(angle, 0, 270, SERVOMIN, SERVOMAX);
}

void setChannel(int channel, float angle) {
  currentAngle[channel] = angle;
  targetAngle[channel] = angle;
  channelActive[channel] = true;
  pwm.setPWM(channel, 0, angleToPulse((int)round(angle)));
}

void setup() {
  Serial.begin(BAUD_RATE);

  pwm.begin();
  pwm.setPWMFreq(50);
  delay(1000);

  for (int ch = 0; ch < NUM_MOTORS; ch++) {
    setChannel(ch, REST_ANGLE[ch]);
  }
}

// Eases every motor back to the rest pose (via stepTowardTargets).
void goToRest() {
  for (int ch = 0; ch < NUM_MOTORS; ch++) {
    targetAngle[ch] = REST_ANGLE[ch];
    channelActive[ch] = true;
  }
}

void loop() {
  // controller.py sends lines like: "0:135,1:90,2:170,5:25\n"
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.equalsIgnoreCase("WHO")) {
      Serial.println("I am Arm");  // lets the PC find this board by name
    } else if (line.length() > 0) {
      applyCommandLine(line);
      lastCommand = millis();
      linked = true;
    }
  }

  unsigned long now = millis();
  if (linked && now - lastCommand > LINK_TIMEOUT_MS) {
    linked = false;
    goToRest();
  }
  if (now - lastUpdate >= UPDATE_INTERVAL_MS) {
    lastUpdate = now;
    stepTowardTargets();
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

      if (channel >= 0 && channel < NUM_CHANNELS) {
        targetAngle[channel] = angle;
        channelActive[channel] = true;
      }
    }

    if (comma == -1) break;
    start = comma + 1;
  }
}

void stepTowardTargets() {
  for (int ch = 0; ch < NUM_CHANNELS; ch++) {
    if (!channelActive[ch]) continue;
    float diff = targetAngle[ch] - currentAngle[ch];
    if (fabs(diff) < 0.1) {
      currentAngle[ch] = targetAngle[ch];
      continue;
    }
    currentAngle[ch] += diff * LERP_FACTOR;
    pwm.setPWM(ch, 0, angleToPulse((int)round(currentAngle[ch])));
  }
}
