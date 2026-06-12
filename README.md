# flustrilo — push-to-talk dictation for Wayland

One hotkey. Speak. Text appears at cursor. Polish-tuned by default; works
for any language Whisper supports.

```
[Client]  hotkey → record mic → POST audio ───▶ [Whisper server]
          ◀── text ── inject at cursor (wtype) ◀──── (any OpenAI-compatible)
```

The client is a ~150-line stdlib Python script. It speaks the OpenAI
`/v1/audio/transcriptions` API, so the backend can be anything that
implements it:

- **self-hosted** [speaches](https://github.com/speaches-ai/speaches)
  (CPU or CUDA) — `vps/docker-compose.yml` is a working template
- **self-hosted** [faster-whisper-server](https://github.com/fedirz/faster-whisper-server)
- **self-hosted** [whisper.cpp server](https://github.com/ggerganov/whisper.cpp/tree/master/examples/server)
- **OpenAI Whisper API** directly — set `FLUSTRILO_URL=https://api.openai.com/v1/audio/transcriptions`
  and `FLUSTRILO_API_KEY=sk-…`

The original use case: Raspberry Pi 4 client + remote VPS (large-v3 too
slow on the Pi). It also runs single-machine — point the client at
`http://127.0.0.1:8000/...` and you have a fully offline dictation rig.

Audio over Tailscale stays inside your tailnet; over a public endpoint
(e.g. OpenAI) it leaves your machine — your call.

## Requirements

**Client machine** (anything running Wayland on Linux):
- `python3` (stdlib only — no pip)
- `wtype` for keystroke injection, `wl-clipboard` for the fallback path
- `libnotify-bin` for toasts
- a mic recorder: `pw-record` (PipeWire) or `arecord` (ALSA) — auto-detected

**Whisper backend** — one of:
- Docker host with CPU or NVIDIA GPU (for the self-hosted template)
- an OpenAI API key

## 1. Pick a backend

### A. Self-host with the included template

```bash
# Copy vps/ to wherever the backend lives (same machine or remote)
scp -r vps/ user@host:~/flustrilo-vps
ssh user@host
cd ~/flustrilo-vps
cp .env.example .env
$EDITOR .env        # set BIND_ADDR and WHISPER_MODEL
docker compose up -d
docker compose logs -f
```

`BIND_ADDR` defaults to `127.0.0.1` (loopback only). On a remote box,
set it to a Tailscale / WireGuard IP — never `0.0.0.0` unless the
server sits behind another firewall.

First request downloads the model (~3 GB for `large-v3`, ~500 MB for
`small`). It's cached in the `hf-cache` named volume so subsequent
container restarts skip the download. To pre-warm offline, run
`docker compose up` once with internet, then disconnect.

Backend variants:

- `latest-cpu` — works anywhere; pick `Systran/faster-whisper-small` or
  `-medium` to keep latency tolerable
- `latest-cuda` — change the image tag and add the NVIDIA runtime; then
  `large-v3` or `-turbo` is realistic

### B. Bring your own server

Any service that responds to `POST /v1/audio/transcriptions` with
`{"text": "..."}` works. Point the client at it via `FLUSTRILO_URL`.

### C. OpenAI Whisper API

No setup. Set on the client:

```
FLUSTRILO_URL=https://api.openai.com/v1/audio/transcriptions
FLUSTRILO_MODEL=whisper-1
FLUSTRILO_API_KEY=sk-...
```

## 2. Install the client

```bash
sudo apt install -y wtype wl-clipboard libnotify-bin pipewire-bin python3
# Or `alsa-utils` if you don't run PipeWire.

mkdir -p ~/.config/flustrilo
cp pi/env.example ~/.config/flustrilo/env
$EDITOR ~/.config/flustrilo/env

install -Dm755 pi/flustrilo.py ~/.local/bin/flustrilo.py
install -Dm755 pi/flustrilo-toggle ~/.local/bin/flustrilo-toggle
```

## 3. Bind the hotkey

Any compositor that can run a shell command on a key works. Two examples:

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

**Sway / Hyprland / river** — equivalent `bindsym` / `bind = ` / `map`.

Reload the compositor.

## 4. Use

Press the hotkey, speak, press again. Toast slot updates in place:
`● nagrywam` → `⏳ rozpoznaję` → `✓ wpisano` (or `⚠ błąd: …`).

## Client config (`~/.config/flustrilo/env`)

| Var | Default | Notes |
|---|---|---|
| `FLUSTRILO_URL` | `http://127.0.0.1:8000/v1/audio/transcriptions` | Full transcription endpoint |
| `FLUSTRILO_MODEL` | `Systran/faster-whisper-large-v3` | Must match a model the backend serves |
| `FLUSTRILO_LANG` | `pl` | ISO 639-1; `en`, `de`, …; empty string = auto-detect |
| `FLUSTRILO_API_KEY` | unset | Sent as `Authorization: Bearer …` if set (for OpenAI etc.) |
| `FLUSTRILO_MAX_SEC` | `600` | Hard cap on a single recording, via `timeout(1)` |

## VPS config (`vps/.env`)

| Var | Default | Notes |
|---|---|---|
| `BIND_ADDR` | `127.0.0.1` | Set to your Tailscale/WireGuard IP for remote access |
| `WHISPER_MODEL` | `Systran/faster-whisper-small` | Any HF Whisper repo speaches understands |
| `WHISPER_COMPUTE_TYPE` | `int8` | `int8` on CPU, `float16` on CUDA |
| `WHISPER_CPU_THREADS` | `4` | Match CPU cores |
| `IMAGE_TAG` | `latest-cpu` | Use `latest-cuda` for GPU |

## Why two halves

Whisper large-v3 on a Pi 4 is minutes-per-sentence; tiny is fast but
butchers Polish. Offloading to a bigger box (or OpenAI) keeps the Pi
recording + typing only.

## Files

```
pi/flustrilo.py        client; ~150 lines, stdlib only
pi/flustrilo-toggle    bash wrapper that loads the env file
pi/env.example         template for ~/.config/flustrilo/env
vps/docker-compose.yml backend template (speaches, OpenAI-compatible)
vps/.env.example       backend config
```

## License

MIT — see `LICENSE`.
