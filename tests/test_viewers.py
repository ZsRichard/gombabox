"""Real SQLite viewer routes, without Pi drivers or background control."""
import ast
import datetime
import logging
import tempfile
import unittest
from pathlib import Path
from flask import Flask, jsonify, request
from sqlalchemy import inspect, text
from models import db, Measurement, CameraCapture, SystemLog, Setting
from core.query_filters import browse_query


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Flask(__name__, instance_path=self.tmp.name)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        names = {'get_system_logs', 'get_db_table_rows', '_ensure_runtime_schema'}
        nodes = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in names)
                 or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DB_TABLES' for t in n.targets))]
        scope = dict(app=self.app, db=db, Measurement=Measurement, CameraCapture=CameraCapture,
                     SystemLog=SystemLog, Setting=Setting, datetime=datetime, request=request,
                     jsonify=jsonify, logger=logging.getLogger(__name__), DEFAULT_LOGS_LIMIT=20,
                     browse_query=browse_query, inspect=inspect, text=text)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
        self.scope = scope
        self.client = self.app.test_client()
        for i in range(6):
            db.session.add(SystemLog(timestamp=datetime.datetime(2026, 10, 4, 10, i),
                                     level='ERROR' if i % 2 else 'INFO',
                                     source='camera' if i % 2 else None,
                                     message=f'capture {i}' if i != 5 else '<script>100%_test</script>'))
        db.session.add(Setting(key='target_humidity', value='90'))
        db.session.commit()

    def tearDown(self):
        db.session.remove(); db.drop_all()
        self.context.pop(); self.tmp.cleanup()

    def test_logs_combined_filter_sort_and_pagination(self):
        data = self.client.get('/api/system/logs?paginated=1&source=camera&level=ERROR&q=capture&direction=asc&limit=1&offset=1').json
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['logs'][0]['message'], 'capture 3')
        legacy = self.client.get('/api/system/logs?paginated=1&source=legacy').json
        self.assertEqual(legacy['total'], 3)
        self.assertEqual(legacy['logs'][0]['source'], 'legacy')

    def test_literal_search_and_injection(self):
        data = self.client.get('/api/db/system_logs?q=100%25_test').json
        self.assertEqual(data['total'], 1)
        data = self.client.get('/api/db/system_logs?q=%27%20OR%201=1%20--').json
        self.assertEqual(data['total'], 0)
        self.assertEqual(SystemLog.query.count(), 6)

    def test_date_end_last_minute_and_generic_filters(self):
        result = self.client.get('/api/db/system_logs?start=2026-10-04T10:02&end=2026-10-04T10:03&sort=id&direction=asc').json
        self.assertEqual([r['message'] for r in result['rows']], ['capture 2', 'capture 3'])
        result = self.client.get('/api/db/system_logs?filter_column=id&filter_op=gte&filter_value=4').json
        self.assertEqual(result['total'], 3)
        self.assertEqual(self.client.get('/api/db/system_logs?filter_column=source&filter_op=null').json['total'], 3)
        self.assertEqual(self.client.get('/api/db/settings?q=humidity').json['total'], 1)

    def test_invalid_queries_are_json_errors(self):
        for query in ['sort=notacolumn', 'direction=DROP', 'filter_column=nope', 'filter_column=id&filter_value=bad',
                      'start=bad', 'start=2026-10-05T00:00&end=2026-10-04T00:00', 'filter_column=id&filter_op=bad']:
            result = self.client.get('/api/db/system_logs?' + query)
            self.assertEqual(result.status_code, 400, query)
            self.assertIn('error', result.json)
        self.assertEqual(self.client.get('/api/db/settings?start=2026-10-04T00:00').status_code, 400)
        self.assertEqual(self.client.get('/api/db/system_logs?limit=-1').json['limit'], 1)

    def test_schema_upgrade_is_idempotent_and_preserves_legacy(self):
        db.session.remove()
        with db.engine.begin() as conn:
            conn.execute(text('DROP TABLE system_logs'))
            conn.execute(text('CREATE TABLE system_logs (id INTEGER PRIMARY KEY, timestamp DATETIME, level TEXT, message TEXT)'))
            conn.execute(text("INSERT INTO system_logs VALUES (1, '2026-10-04 10:00:00', 'INFO', 'existing')"))
        self.scope['_ensure_runtime_schema']()
        self.scope['_ensure_runtime_schema']()
        self.assertEqual(SystemLog.query.get(1).message, 'existing')
        self.assertIsNone(SystemLog.query.get(1).source)


if __name__ == '__main__':
    unittest.main()
