// ARM Fleet Control - talks to controller.py's Fleet mode HTTP API
// (/status, /cmd?motor=&angle=, /reset), served from the same Flask app.

// Colours: the controller serves colour_scheme.xml; apply it over style.css's defaults.
const SCHEME_TO_CSS_VAR = {
  background: "--bg", panel: "--panel", border: "--border",
  text: "--text", text_dim: "--text-dim",
  accent: "--accent", accent_hover: "--accent-hover",
  danger: "--danger", danger_hover: "--danger-hover",
};

fetch("colour_scheme.xml")
  .then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.status))))
  .then((text) => {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    doc.querySelectorAll("colour").forEach((el) => {
      const cssVar = SCHEME_TO_CSS_VAR[el.getAttribute("name")];
      if (cssVar) document.documentElement.style.setProperty(cssVar, el.getAttribute("value"));
    });
  })
  .catch(() => {}); // no scheme available: keep style.css's defaults

const MOTOR_NAMES = {
  1: "Base",
  2: "Shoulder",
  3: "Elbow",
  4: "Wrist Pitch",
  5: "Wrist Roll",
  6: "Claw",
};

const STATUS_POLL_MS = 250;
const SEND_DEBOUNCE_MS = 30;

const motorList = document.getElementById("motorList");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const resetAllBtn = document.getElementById("resetAllBtn");

const sliders = {}; // motor number (string) -> { input, valueEl, dragging }
const sendTimers = {};
let built = false;

function setConnected(connected, label) {
  statusDot.classList.toggle("connected", connected);
  statusText.textContent = label;
}

function buildMotorRows(motors) {
  motorList.innerHTML = "";
  for (const [n, m] of motors) {
    const row = document.createElement("div");
    row.className = "motor-row";

    const top = document.createElement("div");
    top.className = "row-top";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = `Motor ${n}`;
    const name = MOTOR_NAMES[n];
    if (name) {
      const sub = document.createElement("span");
      sub.className = "sub";
      sub.textContent = `- ${name}`;
      label.appendChild(sub);
    }

    const value = document.createElement("span");
    value.className = "value";
    value.textContent = `${m.angle}°`;

    top.appendChild(label);
    top.appendChild(value);

    const input = document.createElement("input");
    input.type = "range";
    input.min = m.min;
    input.max = m.max;
    input.step = 1;
    input.value = m.angle;

    row.appendChild(top);
    row.appendChild(input);
    motorList.appendChild(row);

    const state = { input, valueEl: value, dragging: false };
    sliders[n] = state;

    const stopDragging = () => { state.dragging = false; };
    input.addEventListener("pointerdown", () => { state.dragging = true; });
    input.addEventListener("pointerup", stopDragging);
    input.addEventListener("pointercancel", stopDragging);
    input.addEventListener("input", () => {
      value.textContent = `${input.value}°`;
      sendCommand(n, input.value);
    });
  }
}

function sendCommand(motor, angle) {
  clearTimeout(sendTimers[motor]);
  sendTimers[motor] = setTimeout(() => {
    fetch(`/cmd?motor=${motor}&angle=${angle}`).catch(() => {
      // transient network hiccup - the next status poll will resync the slider
    });
  }, SEND_DEBOUNCE_MS);
}

function applyStatus(data) {
  setConnected(data.connected, data.connected ? "Connected" : "No serial port");

  const motors = Object.entries(data.motors).sort((a, b) => Number(a[0]) - Number(b[0]));

  if (!built) {
    buildMotorRows(motors);
    built = true;
  }

  for (const [n, m] of motors) {
    const state = sliders[n];
    if (!state || state.dragging) continue;
    state.input.value = m.angle;
    state.valueEl.textContent = `${m.angle}°`;
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    applyStatus(await res.json());
  } catch (err) {
    setConnected(false, "Unreachable");
  }
}

resetAllBtn.addEventListener("click", async () => {
  try {
    await fetch("/reset");
  } catch (err) {
    // ignore - fetchStatus below will reflect whatever the real state is
  }
  fetchStatus();
});

fetchStatus();
setInterval(fetchStatus, STATUS_POLL_MS);
