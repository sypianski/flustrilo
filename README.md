# flustrilo — push-to-talk dictation

*flustrilo* — "whisperer" in [Esperanto](https://en.wikipedia.org/wiki/Esperanto) and [Ido](https://sypian.ski/ido).

flustrilo is a push-to-talk dictation client for Wayland. You bind one key in your compositor, press it to start recording, speak, and press it again to stop. The recorded audio is sent to a Whisper-compatible endpoint and the returned text is typed at your cursor.

The microphone is only active while you are holding a recording session.

---

**How it works**

```
hotkey
  |
  v
mic records audio (pw-record / arecord)
  |
  v
POST WAV to Whisper endpoint (local / remote)
  |
  v
text returned
  |
  v
wtype injects text at cursor  (wl-copy fallback for GNOME/KDE)
```

Single Python file, stdlib only, no venv. Toggle state lives in `$XDG_RUNTIME_DIR/flustrilo/`.

---

## Requirements

- Wayland compositor with hotkey binding support
- `wtype` and `wl-clipboard` for text injection
- `libnotify` for desktop toasts
- `pw-record` (PipeWire) or `arecord` (ALSA) for recording
- A running [Whisper-compatible server](#whisper-server) reachable over HTTP

```bash
sudo apt install -y wtype wl-clipboard libnotify-bin pipewire-bin python3
```

---

## Setup

### 1. Configure the endpoint

```bash
mkdir -p ~/.config/flustrilo
cat > ~/.config/flustrilo/env <<'EOF'
FLUSTRILO_URL=http://<server-ip>:8000/v1/audio/transcriptions
FLUSTRILO_MODEL=Systran/faster-whisper-large-v3

# Optional:
# FLUSTRILO_API_KEY=...   # Bearer token, if your server requires auth
# FLUSTRILO_VAD=true      # trim silence (speaches only)
# FLUSTRILO_LANG=en       # language hint; empty = auto-detect
# FLUSTRILO_OUTPUT=cursor # or: clipboard
EOF
```

### 2. Install the script

```bash
install -Dm755 flustrilo.py ~/.local/bin/flustrilo.py
```

Wrapper that loads the env before toggling — needed because compositor keybindings don't source shell profiles:

```bash
cat > ~/.local/bin/flustrilo-toggle <<'EOF'
#!/usr/bin/env bash
set -a; . "$HOME/.config/flustrilo/env"; set +a
exec python3 "$HOME/.local/bin/flustrilo.py" toggle
EOF
chmod +x ~/.local/bin/flustrilo-toggle
```

### 3. Bind a hotkey

**Wayfire** (`~/.config/wayfire.ini`):

```ini
[command]
binding_flustrilo = <super> KEY_D
command_flustrilo = /home/USER/.local/bin/flustrilo-toggle
```

**labwc** (`~/.config/labwc/rc.xml`, inside `<keyboard>`):

```xml
<keybind key="W-d">
  <action name="Execute" command="/home/USER/.local/bin/flustrilo-toggle" />
</keybind>
```

Reload compositor config after editing (logout/login or `labwc --reconfigure`).

---

## Whisper server

flustrilo sends audio to any server implementing the OpenAI `/v1/audio/transcriptions` endpoint.

**[speaches](https://github.com/speaches-ai/speaches)** is the recommended self-hosted option. A `docker-compose.yml` is included in `vps/`:

```bash
# copy to your server and edit the IP binding in docker-compose.yml
docker compose up -d
docker compose logs -f    # wait for "Uvicorn running"
```

First run downloads the model (~3 GB). `WHISPER__TTL=-1` keeps it loaded between requests.

Smoke test:

```bash
curl http://<server-ip>:8000/v1/models
```

For network isolation, bind the port to a private interface (Tailscale, WireGuard, LAN) rather than `0.0.0.0`.

---

## Use

Hotkey → speak → hotkey again → text appears at cursor.

Toasts update in place: `● recording` → `⏳ transcribing` → `✓ typed` / `⚠ empty` / `⚠ error: …`

Double-tap within 1.5 s cancels without transcribing.

---

## Tuning

| Want | Change |
|---|---|
| Faster, slightly less accurate | `FLUSTRILO_MODEL=Systran/faster-whisper-large-v3-turbo` |
| Lower RAM | `...-medium` or `...-small` |
| wtype blocked (GNOME/KDE) | script auto-falls back to wl-copy + paste |
| Clipboard only, no injection | `FLUSTRILO_OUTPUT=clipboard` |

---

## Alternatives

If flustrilo doesn't fit your needs, these projects cover similar ground:

| Project | Language | Approach | Notable difference |
|---|---|---|---|
| [nerd-dictation](https://github.com/ideasman42/nerd-dictation) | Python | VOSK (local, offline) | No Whisper; best if you want fully offline with no server |
| [waystt](https://github.com/sevos/waystt) | Rust | Signal-driven, pipes to wtype | Sends to OpenAI cloud API; outputs stdout, no toasts |
| [whisper-overlay](https://github.com/oddlama/whisper-overlay) | Rust | Streaming overlay, local GPU | Real-time transcription; heavier stack |
| [vocalinux](https://github.com/jatinkrmalik/vocalinux) | Python | GTK4 tray app, multiple engines | Full desktop app; larger dependency tree |

flustrilo's niche: single stdlib-only Python file, any OpenAI-compatible endpoint (local or remote), no pip install required.
