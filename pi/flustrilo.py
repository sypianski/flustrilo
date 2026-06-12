#!/usr/bin/env python3
"""flustrilo — push-to-talk dictation client for Wayland.

Toggle design: bind ONE key in your compositor to `flustrilo.py toggle`.
  1st press  -> start recording (notify "● nagrywam")
  2nd press  -> stop, POST audio to an OpenAI-compatible Whisper endpoint,
                type the returned text at the cursor via wtype.

No always-listening, no network until you stop talking.

Config via env (put in ~/.config/flustrilo/env, sourced by the wrapper):
  FLUSTRILO_URL      full transcription endpoint
  FLUSTRILO_MODEL    model name the backend serves
  FLUSTRILO_LANG     ISO 639-1 code, or empty for auto-detect
  FLUSTRILO_API_KEY  optional Bearer token (e.g. OpenAI)
  FLUSTRILO_MAX_SEC  hard cap per recording
"""
import os
import signal
import subprocess
import sys
import urllib.request
import json
from pathlib import Path

URL = os.environ.get("FLUSTRILO_URL", "http://127.0.0.1:8000/v1/audio/transcriptions")
MODEL = os.environ.get("FLUSTRILO_MODEL", "Systran/faster-whisper-large-v3")
LANG = os.environ.get("FLUSTRILO_LANG", "pl")  # empty string → auto-detect
API_KEY = os.environ.get("FLUSTRILO_API_KEY", "")  # for OpenAI etc.; blank skips header

MAX_SEC = os.environ.get("FLUSTRILO_MAX_SEC", "600")  # cap recording (default 10 min)

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "flustrilo"
RUN.mkdir(parents=True, exist_ok=True)
WAV = RUN / "rec.wav"
PID = RUN / "rec.pid"
LOG = RUN / "debug.log"


def _log(msg: str) -> None:
    with LOG.open("a") as f:
        f.write(msg + "\n")


def notify(msg: str, timeout_ms: int = 1500) -> None:
    """Desktop toast. timeout_ms=0 → persists until replaced/dismissed.

    The synchronous hint makes mako REPLACE the previous flustrilo toast, so
    nagrywam → rozpoznaję → wynik share one slot that updates in place.
    """
    subprocess.run(
        ["notify-send", "-t", str(timeout_ms),
         "-h", "string:x-canonical-private-synchronous:flustrilo",
         "flustrilo", msg],
        stderr=subprocess.DEVNULL)


def recorder_cmd(out: Path) -> list[str]:
    """Pick PipeWire (Pi OS Bookworm) then fall back to ALSA.

    Wrapped in `timeout` so a forgotten start auto-stops after MAX_SEC.
    """
    cap = ["timeout", MAX_SEC]
    if subprocess.run(["which", "pw-record"], capture_output=True).returncode == 0:
        return cap + ["pw-record", "--rate", "16000", "--channels", "1", str(out)]
    return cap + ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", str(out)]


def start() -> None:
    proc = subprocess.Popen(recorder_cmd(WAV))
    PID.write_text(str(proc.pid))
    notify("● nagrywam…  (F21 = stop)", timeout_ms=0)  # persists until stop


def stop_and_transcribe() -> None:
    pid = int(PID.read_text())
    PID.unlink(missing_ok=True)
    try:
        os.kill(pid, signal.SIGINT)  # flush WAV header cleanly
    except ProcessLookupError:
        pass
    # give the recorder a beat to finalize the file
    subprocess.run(["sleep", "0.3"])
    notify("⏳ rozpoznaję…", timeout_ms=0)  # persists until transcription done

    text = transcribe(WAV)
    _log(f"--- stop @ wav={WAV.stat().st_size if WAV.exists() else 0}B "
         f"text={text!r}")
    if not text:
        notify("⚠ pusto", timeout_ms=2000)
        return
    inject(text)
    notify("✓ wpisano", timeout_ms=1200)  # replaces rozpoznaję, auto-dismiss


def transcribe(wav: Path) -> str:
    """POST the WAV to speaches (OpenAI /audio/transcriptions shape)."""
    boundary = "----flustrilo"
    body = bytearray()

    def field(name, value):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())

    field("model", MODEL)
    if LANG:
        field("language", LANG)
    field("response_format", "json")
    field("vad_filter", "true")  # trims silence → faster + cleaner on short clips
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="file"; filename="rec.wav"\r\n')
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(wav.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(URL, data=bytes(body), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("text", "").strip()
    except Exception as e:  # noqa: BLE001 — surface any failure to the user
        notify(f"⚠ błąd: {e}", timeout_ms=5000)
        return ""


def inject(text: str) -> None:
    """Type at cursor. wtype works on wlroots (Wayfire/labwc on Pi OS)."""
    r = subprocess.run(["wtype", text], capture_output=True, text=True)
    _log(f"wtype rc={r.returncode} err={r.stderr.strip()!r}")
    if r.returncode == 0:
        return
    # Fallback: clipboard + paste (works under GNOME/KDE where wtype is blocked).
    subprocess.run(["wl-copy"], input=text.encode())
    r2 = subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                        capture_output=True, text=True)
    _log(f"fallback paste rc={r2.returncode} err={r2.stderr.strip()!r}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if cmd == "toggle":
        (stop_and_transcribe if PID.exists() else start)()
    elif cmd == "start":
        start()
    elif cmd == "stop":
        stop_and_transcribe()
    else:
        sys.exit(f"usage: {sys.argv[0]} [toggle|start|stop]")


if __name__ == "__main__":
    main()
