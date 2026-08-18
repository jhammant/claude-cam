#!/usr/bin/env python3
"""cam - take photos with your iPhone straight into a Claude Code session.

Default flow: a tiny local web server + QR code. Point the iPhone camera at the
QR, tap the banner, tap the shutter. The photo lands on the Mac immediately and
Claude reads it.

Secondary flow ("now"): grab a frame off the iPhone via Continuity Camera with
no interaction on the phone at all. Useful only when the phone is mounted and
pointed at something, because you cannot see what you are framing.
"""
import argparse
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path.home() / ".claude" / "cam"
INBOX = ROOT / "inbox"
SHOTS = ROOT / "shots"
HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CAM_PORT", "8787"))
MAXPX = 1568          # Claude's sweet spot for the long edge
IDLE_EXIT = 60 * 60   # server self-terminates after an hour of silence

last_activity = time.time()


# ---------------------------------------------------------------- helpers

def die(msg, code=1):
    print(f"cam: {msg}", file=sys.stderr)
    sys.exit(code)


def token():
    """Stable per-machine token, so a Home Screen bookmark keeps working."""
    ROOT.mkdir(parents=True, exist_ok=True)
    f = ROOT / "token"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(6))
        f.chmod(0o600)
    return f.read_text().strip()


def lan_ip():
    for iface in ("en0", "en1", "en2"):
        try:
            out = subprocess.run(["ipconfig", "getifaddr", iface],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            if out:
                return out
        except Exception:
            pass
    try:  # fallback: ask the routing table which source address it would use
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def tailscale_ip():
    for exe in ("/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                shutil.which("tailscale") or ""):
        if exe and Path(exe).exists():
            try:
                out = subprocess.run([exe, "ip", "-4"], capture_output=True,
                                     text=True, timeout=3).stdout.strip().splitlines()
                if out:
                    return out[0].strip()
            except Exception:
                pass
    return None


def base_url(host=None):
    return f"http://{host or lan_ip()}:{PORT}/{token()}"


def server_up():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_server():
    if server_up():
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    log = open(ROOT / "server.log", "ab")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"],
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(60):
        if server_up():
            return
        time.sleep(0.1)
    die(f"server did not come up on port {PORT}; see {ROOT/'server.log'}")


def normalise(src: Path, dst: Path):
    """HEIC/whatever -> JPEG, long edge capped at MAXPX. sips ships with macOS."""
    r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(MAXPX),
                        str(src), "--out", str(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        shutil.copy2(src, dst)   # better a big original than nothing


# ---------------------------------------------------------------- server

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _touch(self):
        global last_activity
        last_activity = time.time()

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _split(self):
        """Return (token_from_path, rest) or (None, None)."""
        p = urlparse(self.path).path.strip("/").split("/", 1)
        if not p or not p[0]:
            return None, None
        return p[0], (p[1] if len(p) > 1 else "")

    def do_GET(self):
        self._touch()
        path = urlparse(self.path).path
        if path == "/ping":
            return self._send(200, "ok")
        tok, rest = self._split()
        if tok != token():
            return self._send(404, "not found")
        if rest in ("", "/"):
            page = (HERE / "page.html").read_text()
            return self._send(200, page, "text/html; charset=utf-8")
        if rest == "state":
            n = len(list(INBOX.glob("*.jpg")))
            return self._send(200, json.dumps({"n": n}), "application/json")
        return self._send(404, "not found")

    def do_POST(self):
        self._touch()
        tok, rest = self._split()
        if tok != token():
            return self._send(404, "not found")
        if rest == "done":
            INBOX.mkdir(parents=True, exist_ok=True)
            (INBOX / ".done").write_text(str(time.time()))
            return self._send(200, "ok")
        if rest == "up":
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 80 * 1024 * 1024:
                return self._send(413, "bad size")
            data = self.rfile.read(length)
            q = parse_qs(urlparse(self.path).query)
            name = unquote(q.get("name", ["photo.jpg"])[0])
            ext = (Path(name).suffix or ".jpg").lower()[:6]
            ext = re.sub(r"[^a-z0-9.]", "", ext) or ".jpg"
            INBOX.mkdir(parents=True, exist_ok=True)
            (INBOX / "orig").mkdir(exist_ok=True)
            stamp = f"{time.time():.6f}".replace(".", "")
            raw = INBOX / "orig" / f"{stamp}{ext}"
            raw.write_bytes(data)
            normalise(raw, INBOX / f"{stamp}.jpg")
            return self._send(200, "ok")
        return self._send(404, "not found")


def idle_watchdog(httpd):
    while True:
        time.sleep(30)
        if time.time() - last_activity > IDLE_EXIT:
            httpd.shutdown()
            return


def cmd_serve(args):
    ROOT.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    token()
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=idle_watchdog, args=(httpd,), daemon=True).start()
    print(f"[{time.strftime('%F %T')}] cam serving on {base_url()}", flush=True)
    httpd.serve_forever()


# ---------------------------------------------------------------- get

def show_qr(url, open_window=True):
    qr = shutil.which("qrencode")
    if not qr:
        return
    try:
        art = subprocess.run([qr, "-t", "UTF8", "-m", "2", url],
                             capture_output=True, text=True, timeout=5).stdout
        if art.strip():
            print(art)
    except Exception:
        pass
    if open_window:
        png = ROOT / "qr.png"
        try:
            subprocess.run([qr, "-o", str(png), "-s", "10", "-m", "3", url],
                           capture_output=True, timeout=5)
            subprocess.Popen(["open", str(png)])
        except Exception:
            pass


def park_stale():
    """Never let a shot from a previous run be mistaken for a new one."""
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / "orig").mkdir(exist_ok=True)
    stale = list(INBOX.glob("*.jpg")) + list((INBOX / "orig").glob("*"))
    if stale:
        park = SHOTS / "unclaimed"
        park.mkdir(parents=True, exist_ok=True)
        for f in stale:
            try:
                f.rename(park / f.name)
            except OSError:
                pass
    (INBOX / ".done").unlink(missing_ok=True)


def claim():
    """Move everything in the inbox into a timestamped shots dir."""
    shots = sorted(INBOX.glob("*.jpg"))
    if not shots:
        return []
    dest = SHOTS / time.strftime("%Y%m%d-%H%M%S")
    (dest / "orig").mkdir(parents=True, exist_ok=True)
    out = []
    for i, f in enumerate(shots, 1):
        target = dest / f"{i:02d}.jpg"
        f.rename(target)
        for o in (INBOX / "orig").glob(f"{f.stem}.*"):
            o.rename(dest / "orig" / f"{i:02d}{o.suffix}")
        out.append(target)
    (INBOX / ".done").unlink(missing_ok=True)
    return out


def cmd_get(args):
    ensure_server()
    park_stale()

    url = base_url()
    if not args.no_qr:
        show_qr(url, open_window=not args.no_window)
    print(f"URL  {url}")
    ts = tailscale_ip()
    if ts:
        print(f"TAILSCALE  http://{ts}:{PORT}/{token()}")
    print(f"WAITING  up to {args.timeout}s", flush=True)

    deadline = time.time() + args.timeout
    seen = 0
    while time.time() < deadline:
        shots = sorted(INBOX.glob("*.jpg"))
        seen = len(shots)
        if (INBOX / ".done").exists() and seen:
            break
        if args.n and seen >= args.n:
            break
        time.sleep(0.4)

    out = claim()
    if not out:
        print("PHOTOS 0")
        die("no photos arrived before the timeout", 2)

    print(f"PHOTOS {len(out)}")
    for p in out:
        print(p)


# ---------------------------------------------------------------- now

def continuity_index():
    r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation",
                        "-list_devices", "true", "-i", ""],
                       capture_output=True, text=True)
    best = None
    for line in (r.stderr or "").splitlines():
        m = re.search(r"\[(\d+)\] (.+?)\s*$", line)
        if not m or "audio devices" in line:
            continue
        idx, name = m.group(1), m.group(2)
        if "Desk View" in name or "MacBook" in name or "Capture screen" in name:
            continue
        if "Camera" in name:
            best = (idx, name)
            break
    return best


def cmd_now(args):
    if not shutil.which("ffmpeg"):
        die("ffmpeg not installed (brew install ffmpeg)")
    dev = continuity_index()
    if not dev:
        die("no iPhone Continuity Camera found. Unlock the phone, keep it near "
            "the Mac with Wi-Fi + Bluetooth on, then retry.")
    idx, name = dev
    dest = SHOTS / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for shot in range(1, args.n + 1):
        if shot > 1:
            subprocess.run(["say", "-r", "250", "next"], capture_output=True)
            time.sleep(args.interval)
        tmp = dest / "_f"
        tmp.mkdir(exist_ok=True)
        # Burn ~45 frames so autofocus and exposure settle, then keep the last.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-f", "avfoundation", "-framerate", "30",
                        "-video_size", "1920x1440", "-i", idx,
                        "-frames:v", "45", "-q:v", "3", str(tmp / "%03d.jpg")],
                       capture_output=True)
        frames = sorted(tmp.glob("*.jpg"))
        if not frames:
            shutil.rmtree(tmp, ignore_errors=True)
            die(f"capture from '{name}' failed - is the phone awake and unlocked?")
        target = dest / f"{shot:02d}.jpg"
        normalise(frames[-1], target)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.Popen(["afplay", "/System/Library/Sounds/Pop.aiff"])
        out.append(target)
    print(f"DEVICE {name}")
    print(f"PHOTOS {len(out)}")
    for p in out:
        print(p)


# ---------------------------------------------------------------- preview

def build_preview():
    """Compile the Swift viewfinder on first use, or when the source changes."""
    src, exe = HERE / "campreview.swift", HERE / "campreview"
    if not src.exists():
        die("campreview.swift is missing from the skill directory")
    if exe.exists() and exe.stat().st_mtime >= src.stat().st_mtime:
        return exe
    if not shutil.which("swiftc"):
        die("swiftc not found - install the Xcode command line tools")
    r = subprocess.run(["swiftc", "-O", "-o", str(exe), str(src),
                        "-framework", "AppKit", "-framework", "AVFoundation",
                        "-framework", "CoreImage"], capture_output=True, text=True)
    if r.returncode != 0:
        die("campreview failed to compile:\n" + (r.stderr or "")[-2000:])
    return exe


def cmd_preview(args):
    exe = build_preview()
    park_stale()
    cmd = [str(exe), "--out", str(INBOX)]
    if args.device:
        cmd += ["--device", args.device]
    if args.once:
        cmd.append("--once")
    if args.timer:
        cmd += ["--auto", str(args.timer)]
    r = subprocess.run(cmd)
    if r.returncode == 3:
        print("NO_CAMERA")
        die("no camera found - the phone is asleep or out of range. "
            "Fall back to: cam.py get", 3)

    # The viewfinder writes full-size frames; normalise them like uploads.
    for f in sorted(INBOX.glob("*.jpg")):
        raw = INBOX / "orig" / f"{f.stem}.jpg"
        f.rename(raw)
        normalise(raw, f)

    out = claim()
    if not out:
        print("PHOTOS 0")
        die("the viewfinder closed without capturing anything", 2)
    print(f"PHOTOS {len(out)}")
    for pth in out:
        print(pth)


# ---------------------------------------------------------------- misc

def cmd_url(args):
    print(base_url())
    ts = tailscale_ip()
    if ts:
        print(f"http://{ts}:{PORT}/{token()}")


def cmd_stop(args):
    r = subprocess.run(["pkill", "-f", f"{Path(__file__).name} serve"],
                       capture_output=True)
    print("stopped" if r.returncode == 0 else "not running")


def main():
    ap = argparse.ArgumentParser(prog="cam")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("get", aliases=["upload", "qr", "phone"],
                       help="QR -> phone camera -> photos on the Mac")
    g.add_argument("-n", type=int, default=0, help="return as soon as N photos arrive")
    g.add_argument("--timeout", type=int, default=300)
    g.add_argument("--no-qr", action="store_true", help="URL only, no QR code")
    g.add_argument("--no-window", action="store_true", help="terminal QR only, do not open Preview")
    g.set_defaults(func=cmd_get)

    n = sub.add_parser("now", help="grab a frame off Continuity Camera, no taps")
    n.add_argument("-n", type=int, default=1)
    n.add_argument("--interval", type=float, default=4.0)
    n.set_defaults(func=cmd_now)

    v = sub.add_parser("preview", aliases=["live"],
                       help="live viewfinder window with a capture button")
    v.add_argument("--device", help="camera name substring (default: the iPhone)")
    v.add_argument("--once", action="store_true", help="close after the first capture")
    v.add_argument("--timer", type=float, default=0,
                   help="self-timer: capture N seconds after the window opens, then close")
    v.set_defaults(func=cmd_preview)

    sub.add_parser("serve").set_defaults(func=cmd_serve)
    sub.add_parser("url").set_defaults(func=cmd_url)
    sub.add_parser("stop").set_defaults(func=cmd_stop)

    # The live viewfinder is the default: anything that is not a known
    # subcommand (including nothing at all) is treated as `preview ...`.
    known = set(sub.choices) | {"-h", "--help"}
    argv = sys.argv[1:]
    if not argv or argv[0] not in known:
        argv = ["preview"] + argv

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
