# Screenshot-paste workaround for iPhone → VPS Claude Code

The problem: pasting an image into a terminal-based Claude Code session over SSH is awkward. Claude can read images from local files, but getting a screenshot from your iPhone Photos onto the VPS filesystem is currently a multi-step dance.

Two viable workarounds. Pick one.

---

## Option A — iOS Shortcut + tiny upload endpoint (best UX)

**Result:** Share a screenshot from iOS → 1 tap → `/tmp/sc-<hash>.png` ends up on the VPS and the path is copied to your iPhone clipboard. Paste into Termius. Done.

### 1. Tiny upload service on the VPS

```python
# ~/svc/upload.py — run via systemd or `python3 upload.py`
import hashlib, os, secrets, time
from pathlib import Path
from flask import Flask, request, abort

TOKEN = os.environ["UPLOAD_TOKEN"]
DEST  = Path("/tmp")
MAX   = 25 * 1024 * 1024  # 25 MB

app = Flask(__name__)

@app.post("/upload")
def upload():
    if not secrets.compare_digest(request.headers.get("X-Token", ""), TOKEN):
        abort(401)
    data = request.get_data()
    if len(data) > MAX:
        abort(413)
    name = f"sc-{int(time.time())}-{hashlib.sha1(data).hexdigest()[:8]}.png"
    (DEST / name).write_bytes(data)
    return str(DEST / name) + "\n", 200
```

Run it behind Caddy with a strong path or a one-line auth:

```caddy
# /etc/caddy/Caddyfile
dev.yourdomain.com {
    handle_path /upload {
        reverse_proxy 127.0.0.1:5005
    }
}
```

Generate a token (`openssl rand -hex 32`), export `UPLOAD_TOKEN=...` in the systemd unit.

### 2. iOS Shortcut

Build a Shortcut named "To Claude":
1. **Receive:** Images from Share Sheet
2. **Action:** Get Contents of URL
   - URL: `https://dev.yourdomain.com/upload`
   - Method: POST
   - Headers: `X-Token: <your token>`
   - Request Body: File → Shortcut Input
3. **Action:** Copy to Clipboard ← URL Contents

Add to Share Sheet. Now: screenshot → Share → "To Claude" → paste path into Termius.

---

## Option B — Termius built-in SFTP (zero new infra, more taps)

1. In Termius, open the host's SFTP panel.
2. Tap the upload icon → pick screenshot from Photos.
3. Upload to `/tmp/`.
4. Long-press the resulting file → Copy path.
5. Paste into Claude session.

Slower (~6 taps) but you don't run any extra service.

---

When Termius or Claude Code adds native image paste over SSH, ditch both.
