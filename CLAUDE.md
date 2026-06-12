# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What flustrilo is

Push-to-talk dictation for Wayland. Two halves, glued by HTTP:

- `pi/flustrilo.py` — client. ~150 lines of stdlib Python. One hotkey toggles record/transcribe/inject. Speaks the OpenAI `/v1/audio/transcriptions` API, so the backend is swappable: self-hosted Whisper (speaches / faster-whisper-server / whisper.cpp) or the OpenAI API directly.
- `vps/docker-compose.yml` — reference backend: `speaches-ai/speaches` (CPU or CUDA via `IMAGE_TAG`). All knobs (`BIND_ADDR`, `WHISPER_MODEL`, compute type, threads) are env-driven through `vps/.env`.

Single-machine and remote-VPS deployments are the same code path — only `FLUSTRILO_URL` differs.

## Architecture

State lives in `$XDG_RUNTIME_DIR/flustrilo/`. The client is a toggle FSM:

- `rec.pid` present ⇒ recording. Toggle = SIGINT the recorder, transcribe, inject.
- `rec.pid` absent ⇒ idle. Toggle = spawn `pw-record` (PipeWire, preferred) or `arecord` (ALSA fallback), wrapped in `timeout $FLUSTRILO_MAX_SEC`.
- `rec.wav` — the WAV being written then POSTed.
- `debug.log` — append-only trace.

`notify-send` uses `x-canonical-private-synchronous:flustrilo` so the mako/dunst toast slot updates in place (`nagrywam` → `rozpoznaję` → `wpisano`/`pusto`/`błąd`). Persistent toasts (`timeout=0`) during recording/transcribing are intentional — they get replaced, not stacked.

Transcribe is a multipart POST with `vad_filter=true` (trims silence, faster on short clips). If `FLUSTRILO_API_KEY` is set, it's sent as `Authorization: Bearer …` so OpenAI works as a drop-in backend. If `FLUSTRILO_LANG` is empty, the `language` field is omitted (Whisper auto-detects).

Injection tries `wtype` first (wlroots compositors). On GNOME/KDE where `wtype` is blocked, it falls back to `wl-copy` + `wtype -M ctrl v`.

## Editing rules

- Keep `pi/flustrilo.py` single-file, stdlib-only. No `requests`, no venv. The install target is a stock distro `python3`.
- The compose file must keep `BIND_ADDR` defaulting to `127.0.0.1`. Don't normalize it to `0.0.0.0`.
- Real Tailscale IPs, API keys, hostnames never get committed. `.env` files are gitignored; `*.example` templates are the source of truth.
- Compositor bindings live in user dotfiles, not in this repo.

## Smoke test

```bash
# Backend up?
curl http://127.0.0.1:8000/v1/models

# One-shot end-to-end (skip the toggle)
python3 pi/flustrilo.py start
# …speak…
python3 pi/flustrilo.py stop
tail $XDG_RUNTIME_DIR/flustrilo/debug.log
```

No build, no test suite. After editing the client, reinstall with `install -Dm755 pi/flustrilo.py ~/.local/bin/flustrilo.py`.
