# Portfolio cockpit

A private website over existing operating records. It reads the shared YAML backlog, the Attain product queue, Romance Ops, two local freshness checks, and the existing model-use ledger. It shows all necessary work; the one-hour aspiration never hides items. The first owner action holds one exact shared-backlog item with a reason.

This is a first connected view, not a complete portfolio monitor. Five initiative summaries and four decision cases are dated audit material. A refresh updates source observations, not their business-outcome evidence. Unconnected projects, unavailable sources, cash receipts, allocations, and unproven outcomes stay explicit. The only implemented action is Hold. Notion owner choices still use their existing source links.

## Run a private preview

Install from the reviewed checkout into a dedicated environment. Python 3.11 or later is required.

```sh
python3 -m venv /tmp/portfolio-preview-venv
/tmp/portfolio-preview-venv/bin/pip install '.[cockpit]'
```

Set `COCKPIT_SECRET_KEY` to a random secret of at least 32 characters and `COCKPIT_PASSWORD_HASH` to a Werkzeug password hash. Put neither value in Git, command arguments, screenshots, or this document. Generate them interactively and store the resulting environment file outside the repository with mode 0600. A deployment should load that file through the service manager, not print it.

```sh
/tmp/portfolio-preview-venv/bin/python - <<'PY'
from getpass import getpass
from pathlib import Path
from secrets import token_hex
from werkzeug.security import generate_password_hash
p = Path.home() / '.config/portfolio-cockpit.env'
p.parent.mkdir(parents=True, exist_ok=True)
with p.open('x') as f:
    p.chmod(0o600)
    f.write('COCKPIT_SECRET_KEY=' + token_hex(32) + '\n')
    f.write('COCKPIT_PASSWORD_HASH=' + generate_password_hash(getpass('New cockpit password: ')) + '\n')
PY
```

An existing file is deliberately preserved. Load the file as environment variables using the service manager or a dotenv loader that treats values literally. Do not source an unquoted password hash through a shell: its dollar signs are data.

`portfolio-cockpit --local-http --port 8790` binds only to `127.0.0.1`. This development preview can be reached through the existing authenticated SSH connection using a local port forward. Do not expose its HTTP port to the internet. Actions and remote reads are off by default.

## Proposed permanent placement and budget

Use the current VPS because the authoritative backlog, locks, scoped tokens and installed runners already live there. Keep one Python service; avoid a second task database, queue, or synchronization engine. Put the existing authenticated private access route and TLS in front of loopback. A Cloudflare-hosted static UI would require another backend boundary and offers no demonstrated benefit for this first version.

Proposed initial service limit: one Gunicorn process, four threads, 384 MB memory, no scheduled inference and no new paid hosting commitment. Each owner refresh reads existing records; it does not launch a worker. Allow a bounded two-hour activation and rollback check. These are proposed deployment resources, not an allocation already granted. Public DNS, a new tunnel, or a new hosting bill is not assumed.

For the approved deployment, the service command from a versioned environment is:

```sh
gunicorn --bind 127.0.0.1:8790 --workers 1 --threads 4 --timeout 180 'cockpit.app:create_app()'
```

Run it as the existing owner account that owns the shared backlog locks. Configure the following explicitly:

| Variable | Meaning |
|---|---|
| `COCKPIT_SECRET_KEY`, `COCKPIT_PASSWORD_HASH` | Private signing key and owner password hash. Startup rejects missing configuration. |
| `COCKPIT_HOSTS` | Exact accepted hostnames; default `localhost,127.0.0.1`. |
| `COCKPIT_PUBLIC_ORIGIN` | Exact HTTPS origin used by the owner. Required when the TLS proxy changes the incoming scheme. |
| `COCKPIT_PROJECTS` | Existing projects root; default `~/projects`. |
| `COCKPIT_DOCS_ROOT` | Reviewed repository's `docs` directory. Required for a non-editable wheel install; decision documents are not copied into the wheel. |
| `COCKPIT_REMOTE_READS=1` | Enable read-only Attain and Romance Notion feeds, using each existing scoped token. |
| `COCKPIT_ENABLE_ACTIONS=1` | Enable the tested exact-item Hold action after the live queue action check is approved. |

Use one process so its login rate limit is shared. Behind a private proxy, requests may share an address and hence a limit. Sessions last two hours; rotating the signing key invalidates all of them. Log out removes the browser cookie; this small service has no session-revocation database. Keep access private and TLS enabled. Secure, HttpOnly, SameSite cookies, CSRF checks, accepted hosts and exact Origin checks protect authenticated actions. `Referrer-Policy: same-origin` preserves the Origin on login forms while withholding it from other sites. See [Flask security](https://flask.palletsprojects.com/en/stable/web-security/) and [MDN referrer policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy).

## Action and failure contract

A Hold request includes a signed item revision and explicit owner reason. The server reacquires the runner lock and backlog lock, rereads active and archived records, and rejects stale or duplicate identities. It saves the decision and new state together using the existing atomic YAML writer. Retrying the same accepted action returns its prior result. Other items do not change. No hold request runs a shell command, pushes Git, merges a branch, releases a product, or sends a message.

The queue write is local durable state. This first action does not commit/push the backlog, and therefore does not claim off-device replication. Existing backup/commit processes can capture it later. The live activation check must record the resulting item and verify the expected backup route; do not silently enable a new push pathway. A failed response is not proof that the write failed: refresh before retrying.

Provider acceptance, current heartbeat, human attention, task completion and business benefit remain separate. This version covers queue/report freshness; a full expected-output registry and live cash reconciliation are not implemented. Remote feeds are bounded to 1,000 rows each; excess or partial pagination reports that source unavailable rather than silently dropping work. Large sources should get a specific pagination design only when this boundary is actually reached.

## Verification

```sh
python -m pytest tests/test_cockpit.py tests/test_workqueue_direction.py -q
```

The dev extra includes Flask. Browser tests on 12 September used Chromium at 1440×1100 and 390×844. Login, live read-only feeds, filtering, source cases, no horizontal overflow and no JavaScript errors were checked. Authenticated Hold was also exercised through a browser against a disposable queue. No live queue action occurred during preparation.
