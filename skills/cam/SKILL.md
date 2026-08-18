---
name: cam
description: Show Claude something in the real world using your iPhone camera. Opens a live viewfinder window on the Mac so you can aim the phone and capture what you see; photos land straight in this session. Use for "/cam", "/cam live", "take a photo of this", "let me show you something", "look at this on my desk", "what is this part/label/error", or any time seeing a real object answers the question faster than describing it. For photographing something away from the desk, use the camqr skill instead.
---

# cam — iPhone camera into the session

**Default is the live viewfinder.** A bare `/cam` opens a window on the Mac
showing what the iPhone sees, with a capture button. Everything captured is
printed as a path — **`Read` every printed path**, that is what puts the images
in context.

| The user wants… | Use |
|---|---|
| To show you a thing at their desk (default) | `live` |
| To photograph something in another room / outdoors | `upload` — or the **camqr** skill |
| A grab with zero interaction, phone already aimed | `now` |

## Default: `live` (viewfinder window + capture button)

```bash
python3 ~/.claude/skills/cam/cam.py            # bare = live viewfinder
python3 ~/.claude/skills/cam/cam.py live       # same; `preview` also works
```

Anything that is not a known subcommand is treated as `live`, and flags are
forwarded — so `cam.py --timer 5` works.

Opens a native macOS window with **live video from the iPhone**, a camera
picker, a **Capture** button (or spacebar) and **Send to Claude** (or Return).
The user aims the phone, watches the framing on the Mac, and clicks. They can
capture as many as they like; closing the window also sends. Blocks until the
window closes, then prints `PHOTOS n` and the paths.

- The window floats above other windows so it cannot hide behind a terminal.
- **It takes keyboard focus and spacebar is Capture** — stray typing while it is
  open produces extra frames. Harmless, but do not be surprised by an extra shot.
- First run compiles `campreview.swift` (~2s, cached; auto-rebuilds if edited).
- `--timer N` — self-timer: capture N seconds after the first frame, then close.
- `--once` — close after the first capture. `--device <substr>` — pick a camera.

If it prints `NO_CAMERA` the phone is asleep or out of range: say so and fall
back to `upload` (QR) rather than retrying.

## Away from the desk: `upload` (QR → phone camera)

```bash
python3 ~/.claude/skills/cam/cam.py upload
```

`upload`, `qr`, `phone` and `get` are all the same subcommand, and **`/camqr`**
is a dedicated skill for it. Full details live in that skill — the essentials:

- It prints a QR code, opens the same QR in Preview, and blocks for photos.
- **Copy the QR block from the tool output into your reply in a fenced code
  block**, plus the URL as text. Bash output is not reliably shown to the user.
- `-n 1` returns on the first photo; `--timeout 600` allows more time.

## Hands-free: `now` (Continuity Camera)

```bash
python3 ~/.claude/skills/cam/cam.py now -n 1
```

Grabs a frame with **zero interaction on the phone**. Measured trade-offs:

- **Cold start ~40s** with a sleeping phone; **~5s** once the link is warm.
- **The user cannot see what they are framing** — a face-down phone returns
  pure black.
- The phone must be awake, near the Mac, Wi-Fi + Bluetooth on.

`live` is almost always the better choice; only use `now` when the phone is
already mounted and aimed. If a frame comes back black, say so plainly and
offer `live`.

## Other commands

| Command | Purpose |
|---|---|
| `cam.py url` | Print the upload URL (for bookmarking) without waiting |
| `cam.py --timer 5` | Self-timer capture from the viewfinder |
| `cam.py stop` | Kill the upload server (also self-exits after 1h idle) |

## Notes

- Photos are normalised to JPEG at 1568px on the long edge (Claude's optimal
  size); HEIC is converted automatically and full-res originals kept in `orig/`.
- Everything lands in `~/.claude/cam/shots/<timestamp>/`. Nothing is deleted;
  unclaimed photos from an earlier run move to `shots/unclaimed/`.
- The upload server binds `0.0.0.0` so the phone can reach it, but every path is
  behind a random token. Off-LAN, a Tailscale URL is printed if Tailscale is up.
- If port 8787 is taken, set `CAM_PORT`.
