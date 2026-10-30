# arm_voice.ps1 - ARM's voice for the compiled controllers (C++, C#, Rust, Go, Julia): one line for an
# event, as controller.py's ARM_LINES, in her voice (Zira, slow and low). They start it and carry on.
#   powershell -File arm_voice.ps1 record_on       ARM_VOICE=0 keeps her quiet
param([string]$Event)
if ($env:ARM_VOICE -eq "0") { exit 0 }
$Lines = @{
    connect       = "Arm online. Precisely where I left myself.", "Hello. I can't walk, but I can reach."
    display       = "No serial port. I'll just imagine moving.", "Display only. Pretend I'm moving gracefully."
    remote        = , "Mirroring another arm. Two of us now."
    mode_slider   = , "Sliders. One joint at a time, as it should be."
    mode_joystick = "A joystick. Gentle, please.", "Stick control. I trust you. Mostly."
    mode_ik       = "Inverse kinematics. Tell me where, I'll work out how.", "Give me a point. I'll find the angles."
    mode_fleet    = , "The fleet can see me now. Hello, RIFT."
    record_on     = "Recording. Every move is history now.", "I'm taking notes."
    record_off    = "Saved. I'll remember that.", "Recorded. A small masterpiece."
    play          = "Playing it back. Deja vu.", "From memory, then."
    stop          = , "Stopping. Holding still."
    claw_close    = "Got it.", "Gripping."
    claw_open     = "Letting go.", "Released."
}
if (-not $Lines.ContainsKey($Event)) { exit 1 }
$text = [Security.SecurityElement]::Escape(($Lines[$Event] | Get-Random))
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $s.SelectVoice("Microsoft Zira Desktop") } catch {}
$s.Rate = -2
$s.SpeakSsml("<speak version='1.0' xml:lang='en-US' xmlns='http://www.w3.org/2001/10/synthesis'><prosody pitch='low'>$text</prosody></speak>")
