"""No network or hardware: synthetic snapshots and mocked push transport."""
import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from core.notification_rules import evaluate_snapshot
from core.web_push import install_web_push, validate_subscription


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Flask(__name__, instance_path=self.tmp.name)
        self.snapshot = dict(phase='colonization', running=True,
            measurement=dict(temp=24, hum=90, co2=800, light=0),
            measurement_age_seconds=0, capture_age_seconds=0,
            sample_interval_seconds=60, camera_interval_seconds=3600,
            target_temp=24, target_humidity=90)
        self.monitor = install_web_push(self.app, lambda: self.snapshot)
        self.client = self.app.test_client()
        self.headers = {'X-Notification-Token': 'test-device-' * 5}
        encode = lambda b: base64.urlsafe_b64encode(b).decode().rstrip('=')
        self.sub = dict(endpoint='https://fcm.googleapis.com/test-only',
                        keys=dict(p256dh=encode(b'\x04' + b'x' * 64), auth=encode(b'x' * 16)))

    def tearDown(self):
        self.tmp.cleanup()

    def register(self):
        response = self.client.post('/api/push/device', headers=self.headers,
            json=dict(subscription=self.sub, prefs=dict(delay=30)))
        self.assertEqual(response.status_code, 200)

    def cycle(self, at, send):
        with patch('core.web_push.time.time', return_value=at), patch.object(self.monitor, 'send', send):
            self.monitor.process()

    def test_rules_and_stopped(self):
        self.assertEqual(evaluate_snapshot(self.snapshot), [])
        self.snapshot['measurement'].update(temp=30, co2=0, hum=None, light=-1)
        self.assertEqual({a['key'] for a in evaluate_snapshot(self.snapshot)},
                         {'range_temp', 'invalid_co2', 'invalid_hum', 'invalid_light'})
        self.snapshot['phase'] = 'stopped'
        self.assertEqual(evaluate_snapshot(self.snapshot), [])

    def test_stale(self):
        self.snapshot.update(measurement_age_seconds=181, capture_age_seconds=7201, running=False)
        self.assertEqual({a['key'] for a in evaluate_snapshot(self.snapshot)}, {'stale', 'camera', 'automation'})

    def test_debounce_persistence_and_recovery(self):
        self.register()
        self.snapshot['measurement']['temp'] = 30
        sent = []
        send = lambda sub, event: sent.append(event['key']) or True
        self.cycle(1000, send)
        self.cycle(1029, send)
        self.assertEqual(sent, [])
        self.cycle(1030, send)
        self.cycle(1100, send)
        self.assertEqual(sent, ['range_temp'])
        self.snapshot['measurement']['temp'] = 24
        self.cycle(1110, send)
        self.cycle(1170, send)
        self.assertEqual(sent, ['range_temp', 'recovery_range_temp'])

    def test_failure_retry_and_expired_subscription(self):
        self.register()
        self.snapshot['measurement']['temp'] = 30
        sent = []
        send = lambda sub, event: sent.append(event['key']) or False
        self.cycle(1000, send)
        self.cycle(1030, send)
        self.cycle(1100, send)
        self.assertEqual(len(sent), 1)
        self.cycle(1330, send)
        self.assertEqual(len(sent), 2)
        self.cycle(1630, lambda sub, event: None)
        self.assertFalse(self.client.get('/api/push/device', headers=self.headers).json['subscribed'])

    def test_phase_retry_and_stop_suppression(self):
        self.register()
        self.cycle(1000, lambda *args: True)
        self.snapshot.update(phase='stopped', measurement_age_seconds=None)
        self.cycle(1030, lambda *args: False)
        sent = []
        self.cycle(1330, lambda sub, event: sent.append(event['key']) or True)
        self.assertEqual(sent, ['phase'])

    def test_api_validation_and_opt_out(self):
        self.assertEqual(self.client.post('/api/push/test', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/push/device').status_code, 400)
        for endpoint in ('http://fcm.googleapis.com/test', 'https://127.0.0.1/test', 'https://fcm.googleapis.com.evil.test/x'):
            with self.assertRaises(ValueError):
                validate_subscription(dict(self.sub, endpoint=endpoint))
        self.register()
        self.assertEqual(self.client.post('/api/push/device', headers=self.headers,
            json=dict(subscription=self.sub, prefs=dict(delay=float('nan')))).status_code, 400)
        self.client.delete('/api/push/device', headers=self.headers)
        self.assertFalse(self.client.get('/api/push/device', headers=self.headers).json['subscribed'])

    def test_real_signing_and_encryption_without_network(self):
        key = ec.generate_private_key(ec.SECP256R1())
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.sub['keys']['p256dh'] = base64.urlsafe_b64encode(public).decode().rstrip('=')
        # Mock only HTTP: exercise the real VAPID signer and payload encryption.
        with patch('requests.post') as post:
            post.return_value.status_code = 201
            self.assertTrue(self.monitor.send(self.sub, dict(title='Teszt', detail='Árvíztűrő')))
            self.assertEqual(post.call_count, 1)

    def test_history_read_cursor_and_test_logging(self):
        self.register()
        with patch.object(self.monitor, 'send', return_value=True):
            self.client.post('/api/push/test', headers=self.headers)
        history = self.client.get('/api/push/device', headers=self.headers).json
        self.assertEqual(history['unread'], 1)
        event_id = history['events'][0]['id']
        self.assertEqual(self.client.post('/api/push/read', headers=self.headers, json={'lastId': event_id}).status_code, 200)
        self.assertEqual(self.client.get('/api/push/device', headers=self.headers).json['unread'], 0)
        self.client.post('/api/push/read', headers=self.headers, json={'lastId': 0})
        self.assertEqual(self.client.get('/api/push/device', headers=self.headers).json['lastRead'], event_id)
        other = {'X-Notification-Token': 'other-device-' * 5}
        self.assertEqual(self.client.get('/api/push/device', headers=other).json['events'], [])
        with self.monitor.connect() as db:
            db.execute('DELETE FROM events')
            db.execute('UPDATE devices SET last_test=0')
        with patch.object(self.monitor, 'send', return_value=True):
            self.client.post('/api/push/test', headers=self.headers)
        self.assertEqual(self.client.get('/api/push/device', headers=self.headers).json['unread'], 1)

    def test_test_notification_works_when_stopped_and_errors_are_json(self):
        self.register()
        self.snapshot['phase'] = 'stopped'
        with patch.object(self.monitor, 'send', return_value=True):
            self.assertEqual(self.client.post('/api/push/test', headers=self.headers).status_code, 200)
        with self.monitor.connect() as db:
            db.execute('UPDATE devices SET last_test=0')
        with patch('core.web_push.webpush', side_effect=ValueError('test signing failure')):
            response = self.client.post('/api/push/test', headers=self.headers)
            self.assertEqual(response.status_code, 502)
            self.assertTrue(response.is_json)


if __name__ == '__main__':
    unittest.main()
