# GombaBox Web Push

The server sends encrypted Web Push messages through the browser's push provider.
The PWA does not need to be open, but the Pi must be running and have internet
access. Delivery also depends on browser/OS notification permissions and network
availability. Total Pi outage detection is deliberately not implemented yet.

## Enable on each device

Open Settings → Értesítések, configure limits and save, then choose
“Telefonos értesítések engedélyezése” and grant browser permission.
Use “Próbaértesítés” to verify delivery. On iOS/iPadOS 16.4 or newer, use the
Home Screen web app. This is also supported in compatible desktop browsers.

Default persistence delay is 120 seconds; recovery requires 60 seconds of
normal readings. The monitor checks every 30 seconds. A continuing fault sends
once after the delay, not on every reading. Failed deliveries retry after five
minutes; expired subscriptions are removed. Stopped suppresses growing alerts.
Phase changes are reported independently. The foreground connection warning
is not an external Pi outage monitor.

Rules cover temperature/humidity deviations from configured targets, high CO₂,
invalid temperature/humidity/CO₂/light readings, stale measurements, delayed
captures, and stopped automation. Zero illuminance is valid, not a lamp failure.
Plausible but stuck readings cannot reliably identify a broken sensor.

## Operations

Install `requirements-notifications.txt` in the service virtual environment.
The current direct `app.py` service starts the daemon monitor. A future WSGI
deployment must explicitly provide one monitoring worker, not one per worker
process.

`instance/webpush/vapid.pem` and `notifications.sqlite3` must be kept private
and retained across deployments. The SQLite database stores per-device
subscriptions, preferences, persistent alert state, and 30 days of send history.
Never commit the private key or subscription database. Losing the VAPID key
requires browser re-subscription. The sensor/capture database is unchanged.
The UI stores a random device-management token in local storage; clearing site
data may require re-enabling notifications. Treat the existing Tailscale-only
access boundary as required; this is not a public multi-user authorization layer.

Tests: `python -m unittest discover -s tests -p test_web_push.py -v`.
These tests use synthetic measurements and a mocked transport; actual device
delivery requires the opt-in/test steps above.
