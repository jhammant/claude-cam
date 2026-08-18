---
name: camqr
description: Take a photo with your phone from anywhere via a QR code — scan it, the normal camera opens, and the photos land in this Claude Code session. Use for "/camqr", "/cam upload", or whenever the subject is away from the desk, in another room, or outside, where the Mac's live viewfinder cannot see it. Works with any phone that has a camera and a browser.
---

# camqr — QR → phone camera → session

The away-from-the-desk half of the [`cam`](../cam/SKILL.md) skill. Use this when
the subject is **not in front of the Mac** — another room, the garage, outdoors.
If the user is at their desk and can point the phone at the thing, `/cam` (live
viewfinder) is faster and lets them see the framing.

Unlike the viewfinder, this mode needs no Continuity Camera and no iPhone — any
phone with a camera and a browser works.

```bash
python3 ~/.claude/skills/cam/cam.py upload
```

Starts a local web server (port 8787, path-token gated), prints a QR code, opens
the same QR in Preview, then **blocks** until photos arrive and prints:

```text
URL  http://192.168.1.42:8787/<token>
WAITING  up to 300s
PHOTOS 2
/Users/you/.claude/cam/shots/20260818-125046/01.jpg
/Users/you/.claude/cam/shots/20260818-125046/02.jpg
```

**Then `Read` every printed path** — that is what puts the images in context.

## Critical: show the QR

Bash output is not reliably rendered to the user, so **copy the QR block out of
the tool output into your reply, inside a fenced code block**, plus the URL as a
text fallback. Without it there is nothing to scan.

## What they see on the phone

Scan → browser opens → **Take Photo** (rear camera, one tap) → shutter →
thumbnail → a 4-second countdown auto-sends, or **＋ Another photo** to keep
going, or **Send now**. Batches of several photos are normal.

**First time only**: Share → *Add to Home Screen* makes it a permanent one-tap
icon (port and token are stable, so the URL never changes).

## Flags

- `-n 1` — return the instant the first photo lands.
- `--timeout 600` — allow more time to go and find the thing.
- `--no-qr` / `--no-window` — once it is on the Home Screen.

`upload`, `qr`, `phone` and `get` are all the same subcommand. Off the local
network, the printed Tailscale URL works if the phone is on the same tailnet.
See the `cam` skill for the viewfinder and hands-free modes.
