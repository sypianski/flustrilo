#!/usr/bin/env python3
"""flustrilo — push-to-talk dictation client for Wayland.

Toggle design: bind ONE key in your compositor to `flustrilo.py toggle`.
  1st press  -> start recording (notify "● recording")
  2nd press  -> stop, send audio to the transcription server, type the
                returned text at the cursor via wtype.

No always-listening, no network until you stop talking.

Config via env (put in ~/.config/flustrilo/env, sourced by the wrapper):

  FLUSTRILO_URL      Full transcription endpoint.
                     Examples:
                       https://api.openai.com/v1/audio/transcriptions  (OpenAI)
                       http://192.168.1.x:8000/v1/audio/transcriptions  (VPS)
                       http://127.0.0.1:8000/v1/audio/transcriptions    (local)
                     Required — no default (fail-loud beats silently doing nothing).

  FLUSTRILO_API_KEY  Bearer token.  Set for OpenAI or any authenticated endpoint.
                     Leave unset for unauthenticated local / VPS servers.

  FLUSTRILO_MODEL    Model name passed to the endpoint.
                     OpenAI:   whisper-1
                     speaches: Systran/faster-whisper-large-v3
                     local:    whatever your server loads by default

  FLUSTRILO_LANG     BCP-47 language hint (e.g. en, pl, ar).  Empty = auto-detect.

  FLUSTRILO_VAD      Set to "true" to send vad_filter=true (speaches only;
                     ignored/rejected by OpenAI).  Default: false.

  FLUSTRILO_MAX_SEC  Hard recording cap in seconds.  Default: 600.

  FLUSTRILO_OUTPUT   cursor    (default) type at cursor via wtype;
                               fall back to clipboard+paste if wtype fails.
                     clipboard copy to clipboard only, no keystroke injection.
"""
import os
import signal
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Config — load ~/.config/flustrilo/env first so compositor bindings
# (which don't source shell profiles) pick up user settings.
# ---------------------------------------------------------------------------
_env_file = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "flustrilo" / "env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ[_k.strip()] = _v.strip()

URL     = os.environ.get("FLUSTRILO_URL", "")
API_KEY = os.environ.get("FLUSTRILO_API_KEY", "")
MODEL   = os.environ.get("FLUSTRILO_MODEL", "whisper-1")
LANG    = os.environ.get("FLUSTRILO_LANG", "")
VAD     = os.environ.get("FLUSTRILO_VAD", "false").lower() == "true"
MAX_SEC = os.environ.get("FLUSTRILO_MAX_SEC", "600")
OUTPUT  = os.environ.get("FLUSTRILO_OUTPUT", "cursor")

# ---------------------------------------------------------------------------
# Runtime paths
# ---------------------------------------------------------------------------
RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "flustrilo"
RUN.mkdir(parents=True, exist_ok=True)
WAV  = RUN / "rec.wav"
PID  = RUN / "rec.pid"
TS   = RUN / "rec.start"
TPID = RUN / "transcribing.pid"
LOG  = RUN / "debug.log"

TRANSCRIPT_DIR = Path.home() / ".local" / "share" / "flustrilo"
TRANSCRIPT     = TRANSCRIPT_DIR / "transcript.jsonl"
TRANSCRIPT_TTL = 86400  # seconds — older entries pruned on each write

CANCEL_SEC = 1.5  # second press within this window cancels instead of transcribing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:
    with LOG.open("a") as f:
        f.write(msg + "\n")


def _save_transcript(text: str) -> None:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cutoff = now - TRANSCRIPT_TTL
    lines = []
    if TRANSCRIPT.exists():
        for line in TRANSCRIPT.read_text().splitlines():
            try:
                if json.loads(line).get("ts", 0) > cutoff:
                    lines.append(line)
            except (json.JSONDecodeError, KeyError):
                pass
    lines.append(json.dumps({"ts": now, "text": text}, ensure_ascii=False))
    TRANSCRIPT.write_text("\n".join(lines) + "\n")


def notify(summary: str, body: str = "", timeout_ms: int = 1500) -> None:
    """Desktop toast.

    The synchronous hint makes mako REPLACE the previous flustrilo toast so
    recording → transcribing → result share one slot that updates in place.
    """
    cmd = ["notify-send", "-t", str(timeout_ms),
           "-h", "string:x-canonical-private-synchronous:flustrilo",
           summary]
    if body:
        cmd.append(body)
    subprocess.run(cmd, stderr=subprocess.DEVNULL)


def recorder_cmd(out: Path) -> list:
    """Pick PipeWire then fall back to ALSA.

    Wrapped in `timeout` so a forgotten start auto-stops after MAX_SEC.
    """
    cap = ["timeout", MAX_SEC]
    if subprocess.run(["which", "pw-record"], capture_output=True).returncode == 0:
        return cap + ["pw-record", "--rate", "16000", "--channels", "1", str(out)]
    return cap + ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", str(out)]


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def start() -> None:
    if not URL:
        notify("⚠ flustrilo", "FLUSTRILO_URL not set", timeout_ms=5000)
        sys.exit("FLUSTRILO_URL is required")
    proc = subprocess.Popen(recorder_cmd(WAV))
    PID.write_text(str(proc.pid))
    TS.write_text(str(time.time()))
    notify("● recording…", "toggle = stop  ·  double-tap = cancel", timeout_ms=0)


def cancel() -> None:
    _log(f"--- cancel called, pid_exists={PID.exists()}")
    if not PID.exists():
        return
    pid = int(PID.read_text())
    PID.unlink(missing_ok=True)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    WAV.unlink(missing_ok=True)
    TS.unlink(missing_ok=True)
    notify("✗ cancelled", timeout_ms=1500)
    _log("--- cancel")


def stop_and_transcribe() -> None:
    pid = int(PID.read_text())
    PID.unlink(missing_ok=True)
    TS.unlink(missing_ok=True)
    try:
        os.kill(pid, signal.SIGINT)  # flush WAV header cleanly
    except ProcessLookupError:
        pass
    subprocess.run(["sleep", "0.3"])
    TPID.write_text(str(os.getpid()))
    notify("⏳ transcribing…", "toggle = cancel", timeout_ms=0)

    text = transcribe(WAV)
    TPID.unlink(missing_ok=True)
    _log(f"--- stop  wav={WAV.stat().st_size if WAV.exists() else 0}B  text={text!r}")

    if not text:
        notify("⚠ empty", timeout_ms=2000)
        return
    _save_transcript(text)
    inject(text)
    if OUTPUT == "clipboard":
        preview = text[:140].rsplit(" ", 1)[0] + "…" if len(text) > 140 else text
        notify("✓ copied", preview, timeout_ms=4000)
    else:
        notify("✓ typed", timeout_ms=1200)


def transcribe(wav: Path) -> str:
    """POST the WAV to an OpenAI-compatible /audio/transcriptions endpoint."""
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
    if VAD:
        # speaches-specific; OpenAI and most local servers reject this field
        field("vad_filter", "true")

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
    except Exception as e:
        notify(f"⚠ error: {e}", timeout_ms=5000)
        _log(f"--- transcribe error: {e}")
        return ""


def inject(text: str) -> None:
    """Deliver transcription according to FLUSTRILO_OUTPUT."""
    if OUTPUT == "clipboard":
        subprocess.run(["wl-copy"], input=text.encode())
        _log("clipboard-only mode")
        return
    r = subprocess.run(["wtype", text], capture_output=True, text=True)
    _log(f"wtype rc={r.returncode} err={r.stderr.strip()!r}")
    if r.returncode == 0:
        return
    # Fallback: clipboard + paste (works under GNOME/KDE where wtype is blocked)
    subprocess.run(["wl-copy"], input=text.encode())
    r2 = subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                        capture_output=True, text=True)
    _log(f"fallback paste rc={r2.returncode} err={r2.stderr.strip()!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if cmd == "toggle":
        if TPID.exists():
            try:
                os.kill(int(TPID.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
            TPID.unlink(missing_ok=True)
            WAV.unlink(missing_ok=True)
            notify("✗ cancelled", timeout_ms=1500)
            _log("--- cancel during transcription")
        elif PID.exists():
            elapsed = time.time() - float(TS.read_text()) if TS.exists() else 9999
            (cancel if elapsed < CANCEL_SEC else stop_and_transcribe)()
        else:
            start()
    elif cmd == "start":
        start()
    elif cmd == "stop":
        stop_and_transcribe()
    elif cmd == "cancel":
        cancel()
    else:
        sys.exit(f"usage: {sys.argv[0]} [toggle|start|stop|cancel]")


if __name__ == "__main__":
    main()
