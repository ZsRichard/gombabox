"""Persistent per-device Web Push monitoring, separate from growing controls."""
import base64
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

from flask import jsonify, request
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import webpush, WebPushException
from core.notification_rules import evaluate_snapshot


def validate_preferences(raw):
    result = {}
    for key, default, lower, upper in [('temp_margin', 2, .1, 20), ('humidity_margin', 10, 1, 100), ('co2_limit', 1500, 400, 10000), ('delay', 120, 30, 3600)]:
        value = float(raw.get(key, default))
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError('Érvénytelen riasztási határérték.')
        result[key] = value
    for key in ('enabled', 'recovery'):
        value = raw.get(key, True)
        if not isinstance(value, bool):
            raise ValueError('Érvénytelen beállítás.')
        result[key] = value
    return result


def validate_subscription(sub):
    endpoint = sub['endpoint']
    url = urlparse(endpoint)
    host = url.hostname or ''
    allowed = host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com') or host.endswith('.notify.windows.com') or host.endswith('.push.apple.com')
    if not allowed or url.scheme != 'https' or url.port not in (None, 443) or url.username or url.password or url.fragment or len(endpoint) > 4096:
        raise ValueError('Nem támogatott push-szolgáltató.')
    for key, size in [('p256dh', 65), ('auth', 16)]:
        encoded = sub['keys'][key]
        decoded = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        if len(decoded) != size:
            raise ValueError('Érvénytelen böngészőkulcs.')
    return {'endpoint': endpoint, 'keys': {k: sub['keys'][k] for k in ('p256dh', 'auth')}}


class PushMonitor:
    def __init__(self, app, snapshot):
        self.app, self.snapshot = app, snapshot
        self.directory = os.path.join(app.instance_path, 'webpush')
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        self.keyfile = os.path.join(self.directory, 'vapid.pem')
        if not os.path.exists(self.keyfile):
            key = ec.generate_private_key(ec.SECP256R1())
            with os.fdopen(os.open(self.keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
                handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with open(self.keyfile, 'rb') as handle:
            key = serialization.load_pem_private_key(handle.read(), password=None)
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.public_key = base64.urlsafe_b64encode(public).decode().rstrip('=')
        self.dbfile = os.path.join(self.directory, 'notifications.sqlite3')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS devices (token TEXT PRIMARY KEY, subscription TEXT NOT NULL, prefs TEXT NOT NULL, state TEXT NOT NULL DEFAULT "{}", last_test REAL NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, token TEXT, created REAL, title TEXT, detail TEXT, delivered INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS receipts (token TEXT PRIMARY KEY, last_id INTEGER NOT NULL DEFAULT 0)')
        os.chmod(self.dbfile, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.dbfile, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def send(self, sub, event):
        try:
            webpush(subscription_info=sub, data=json.dumps(event, ensure_ascii=False), vapid_private_key=self.keyfile,
                    vapid_claims={'sub': 'https://richard-pi.tail81c38b.ts.net'}, ttl=3600, timeout=10)
            return True
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                return None
            self.app.logger.warning('Web Push delivery failed (HTTP %s)', status)
            return False
        except Exception as exc:
            # Do not log subscription endpoints, keys, or provider response bodies.
            self.app.logger.error('Web Push preparation/transport failed (%s)', type(exc).__name__)
            return False

    def log_event(self, db, token, created, title, detail, delivered):
        # Keep IDs above read cursors even after retention removes every event.
        db.execute('INSERT INTO events(id,token,created,title,detail,delivered) VALUES((SELECT MAX(n)+1 FROM (SELECT COALESCE(MAX(id),0) AS n FROM events UNION ALL SELECT COALESCE(MAX(last_id),0) AS n FROM receipts)),?,?,?,?,?)',
                   (token, created, title, detail, int(bool(delivered))))

    def process(self):
        snapshot = self.snapshot()
        now = time.time()
        with self.connect() as db:
            devices = db.execute('SELECT * FROM devices').fetchall()
        for device in devices:
            prefs = json.loads(device['prefs'])
            if not prefs['enabled']:
                continue
            state = json.loads(device['state'])
            previous_phase = state.get('_phase')
            state['_phase'] = snapshot['phase']
            events = []
            pending = state.setdefault('_pending', [])
            if previous_phase is not None and previous_phase != snapshot['phase']:
                names = {'stopped': 'Szüneteltetve', 'colonization': 'Inkubáció', 'fruiting': 'Termő szakasz'}
                pending.append(dict(key='phase', title='Üzemmód változott', detail=names.get(snapshot['phase'], snapshot['phase'])))
            alerts = evaluate_snapshot(snapshot, prefs['temp_margin'], prefs['humidity_margin'], prefs['co2_limit'])
            active = {a['key']: a for a in alerts}
            for key, alert in active.items():
                entry = state.setdefault(key, {'since': now, 'sent': False, 'title': alert['title'], 'retry': 0})
                entry.pop('clear_since', None)
                if not entry['sent'] and now - entry['since'] >= prefs['delay'] and now >= entry.get('retry', 0):
                    events.append(alert)
            for key in list(state):
                if key.startswith('_') or key in active:
                    continue
                entry = state[key]
                if snapshot['phase'] == 'stopped':
                    del state[key]
                    continue
                entry.setdefault('clear_since', now)
                if now - entry['clear_since'] >= 60:
                    if entry['sent'] and prefs['recovery']:
                        pending.append(dict(key='recovery_' + key, title='Visszaellenőrzési jelzés lezárva' if key.startswith('response_') else 'Helyreállt az állapot', detail=entry['title'] + (' – A jelzés már nem aktív; ez önmagában nem bizonyítja az eszköz helyreállását.' if key.startswith('response_') else '')))
                    del state[key]
            events.extend(event for event in pending if now >= event.get('retry', 0))
            expired = False
            for event in events:
                result = self.send(json.loads(device['subscription']), event)
                if result is None:
                    expired = True
                    break
                if event['key'] in state:
                    state[event['key']]['sent'] = result
                    state[event['key']]['retry'] = now + 300
                elif event in pending:
                    if result:
                        pending.remove(event)
                    else:
                        event['retry'] = now + 300
                with self.connect() as db:
                    self.log_event(db, device['token'], now, event['title'], event['detail'], result)
            with self.connect() as db:
                if expired:
                    db.execute('DELETE FROM devices WHERE token=?', (device['token'],))
                else:
                    db.execute('UPDATE devices SET state=? WHERE token=? AND prefs=?', (json.dumps(state), device['token'], device['prefs']))
                db.execute('DELETE FROM events WHERE created < ?', (now - 30 * 86400,))

    def start(self):
        def run():
            while True:
                try:
                    with self.app.app_context():
                        self.process()
                except Exception:
                    self.app.logger.error('Notification monitoring cycle failed')
                time.sleep(30)
        threading.Thread(target=run, name='web-push-monitor', daemon=True).start()


def install_web_push(app, snapshot):
    monitor = PushMonitor(app, snapshot)

    @app.route('/api/push/key')
    def push_key():
        return jsonify(publicKey=monitor.public_key)

    @app.route('/api/push/device', methods=['POST', 'DELETE', 'GET'])
    def push_device():
        token = request.headers.get('X-Notification-Token', '')
        if len(token) < 32 or len(token) > 200:
            return jsonify(error='Hiányzó eszközazonosító.'), 400
        token = hashlib.sha256(token.encode()).hexdigest()
        if request.method != 'GET' and request.headers.get('Origin') not in (None, request.host_url.rstrip('/'), 'https://richard-pi.tail81c38b.ts.net'):
            return jsonify(error='Invalid origin'), 403
        with monitor.connect() as db:
            if request.method == 'DELETE':
                db.execute('DELETE FROM devices WHERE token=?', (token,))
                db.execute('DELETE FROM events WHERE token=?', (token,))
                return jsonify(ok=True)
            if request.method == 'GET':
                rows = db.execute('SELECT id,created,title,detail,delivered FROM events WHERE token=? ORDER BY id DESC LIMIT 50', (token,)).fetchall()
                receipt = db.execute('SELECT last_id FROM receipts WHERE token=?', (token,)).fetchone()
                last_read = receipt['last_id'] if receipt else 0
                unread = db.execute('SELECT count(*) FROM events WHERE token=? AND id>?', (token, last_read)).fetchone()[0]
                device = db.execute('SELECT state FROM devices WHERE token=?', (token,)).fetchone()
                return jsonify(subscribed=device is not None, events=[dict(r) for r in rows], lastRead=last_read, unread=unread)
            try:
                payload = request.get_json()
                sub = validate_subscription(payload['subscription'])
                prefs = validate_preferences(payload.get('prefs', {}))
            except (KeyError, TypeError, ValueError):
                return jsonify(error='Érvénytelen feliratkozás vagy határérték.'), 400
            existing = db.execute('SELECT token FROM devices WHERE subscription=?', (json.dumps(sub),)).fetchone()
            if existing and existing['token'] != token:
                return jsonify(error='Ez a feliratkozás már másik eszközazonosítóhoz tartozik.'), 409
            if db.execute('SELECT count(*) FROM devices').fetchone()[0] >= 50 and not db.execute('SELECT 1 FROM devices WHERE token=?', (token,)).fetchone():
                return jsonify(error='Túl sok eszköz.'), 409
            db.execute('INSERT INTO devices(token,subscription,prefs) VALUES(?,?,?) ON CONFLICT(token) DO UPDATE SET subscription=excluded.subscription,prefs=excluded.prefs,state="{}"', (token, json.dumps(sub), json.dumps(prefs)))
        return jsonify(ok=True)

    @app.route('/api/push/read', methods=['POST'])
    def push_read():
        raw_token = request.headers.get('X-Notification-Token', '')
        if not 32 <= len(raw_token) <= 200:
            return jsonify(error='Hiányzó eszközazonosító.'), 400
        token = hashlib.sha256(raw_token.encode()).hexdigest()
        payload = request.get_json(silent=True) or {}
        last_id = payload.get('lastId')
        if type(last_id) is not int or last_id < 0:
            return jsonify(error='Érvénytelen üzenetazonosító.'), 400
        with monitor.connect() as db:
            maximum = db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE token=?', (token,)).fetchone()[0]
            last_id = min(last_id, maximum)
            db.execute('INSERT INTO receipts(token,last_id) VALUES(?,?) ON CONFLICT(token) DO UPDATE SET last_id=MAX(receipts.last_id,excluded.last_id)', (token, last_id))
        return jsonify(ok=True)

    @app.route('/api/push/test', methods=['POST'])
    def push_test():
        token = hashlib.sha256(request.headers.get('X-Notification-Token', '').encode()).hexdigest()
        with monitor.connect() as db:
            row = db.execute('SELECT * FROM devices WHERE token=?', (token,)).fetchone()
            if not row:
                return jsonify(error='Előbb engedélyezd a Web Push értesítéseket.'), 404
            if time.time() - row['last_test'] < 60:
                return jsonify(error='Próbaértesítés percenként egyszer küldhető.'), 429
            db.execute('UPDATE devices SET last_test=? WHERE token=?', (time.time(), token))
        delivered = monitor.send(json.loads(row['subscription']), dict(key='test', title='GombaBox próbaértesítés', detail='A szerver elküldte a Web Push üzenetet.'))
        with monitor.connect() as db:
            monitor.log_event(db, token, time.time(), 'GombaBox próbaértesítés', 'Próbaértesítés küldése.', delivered)
        return (jsonify(ok=True) if delivered else (jsonify(error='A push-szolgáltató nem fogadta el az üzenetet.'), 502))
    return monitor
