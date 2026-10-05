"""Exercise the actual chart routes with SQLite, without starting Pi hardware."""
import ast
import datetime
import logging
import tempfile
import unittest
from pathlib import Path

from flask import Flask, jsonify, request
from sqlalchemy import func, or_
from models import db, Measurement, CameraCapture, GrowthPhasePeriod


class ChartHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Flask(__name__, instance_path=self.tmp.name)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        # Execute the production routes, excluding module-level hardware setup.
        names = {'_parse_client_datetime', '_resolve_history_window', '_evenly_sample',
                 '_history_window_is_fruiting', '_capture_analysis_value', '_parse_analysis_value',
                 'get_history_availability', 'get_measurements_history', 'get_camera_history'}
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        module = ast.Module(body=[node for node in tree.body
                                 if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
        scope = dict(app=self.app, db=db, Measurement=Measurement, CameraCapture=CameraCapture,
                     GrowthPhasePeriod=GrowthPhasePeriod,
                     datetime=datetime, request=request, jsonify=jsonify, func=func, or_=or_,
                     CHART_HISTORY_MAX_POINTS=1000, CHART_HISTORY_MAX_DAYS=730,
                     logger=logging.getLogger(__name__))
        exec(compile(module, 'app.py', 'exec'), scope)
        self.scope = scope
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.tmp.cleanup()

    def add_measurement(self, timestamp):
        db.session.add(Measurement(timestamp=timestamp, temperature=20, humidity=90,
                                   pressure=1000, co2=800, light=5))

    def test_calendar_end_includes_last_minute_only(self):
        self.add_measurement(datetime.datetime(2026, 6, 20, 23, 59, 59, 900000))
        self.add_measurement(datetime.datetime(2026, 6, 21))
        db.session.add(CameraCapture(timestamp=datetime.datetime(2026, 6, 20, 23, 59, 30),
                                     filename='test.jpg', analysis_result='50%'))
        db.session.commit()
        query = '?start=2026-06-18T00:00&end=2026-06-20T23:59'
        for endpoint in ('measurements', 'camera'):
            response = self.client.get(f'/api/{endpoint}/history{query}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['count'], 1)

    def test_sampling_keeps_both_endpoints(self):
        first = datetime.datetime(2026, 6, 3)
        for i in range(2000):
            self.add_measurement(first + datetime.timedelta(seconds=i))
        db.session.commit()
        data = self.client.get('/api/measurements/history?start=2026-06-03T00:00&end=2026-06-03T01:00').json
        self.assertEqual(data['count'], 2000)
        self.assertLessEqual(data['returned_count'], 1000)
        self.assertEqual(data['measurements'][0]['time'], '2026-06-03 00:00')
        self.assertEqual(data['measurements'][-1]['time'], '2026-06-03 00:33')

    def test_phase_color_does_not_imply_recorded_data(self):
        db.session.add(GrowthPhasePeriod(phase='fruiting', start_time=datetime.datetime(2026, 6, 12),
                                        end_time=datetime.datetime(2026, 7, 19)))
        self.add_measurement(datetime.datetime(2026, 6, 12, 5))
        db.session.commit()
        empty = self.client.get('/api/measurements/history?start=2026-06-18T00:00&end=2026-06-20T23:59')
        self.assertEqual(empty.json['count'], 0)
        availability = self.client.get('/api/history/availability')
        self.assertEqual(availability.status_code, 200)
        self.assertEqual(availability.json['days'], [dict(date='2026-06-12', measurements=1, captures=0,
                            measurements_first='2026-06-12T05:00:00', measurements_last='2026-06-12T05:00:00')])

    def test_invalid_ranges_return_json_error(self):
        for query in ('start=bad&end=2026-06-20T23:59', 'start=2026-06-20T00:00',
                      'start=2026-06-20T00:00&end=2026-06-18T00:00'):
            response = self.client.get('/api/measurements/history?' + query)
            self.assertEqual(response.status_code, 400)
            self.assertIn('error', response.json)

    def test_fruiting_window_and_null_coverage(self):
        db.session.add(GrowthPhasePeriod(phase='fruiting', start_time=datetime.datetime(2026, 6, 12),
                                        end_time=datetime.datetime(2026, 7, 19)))
        db.session.add(CameraCapture(timestamp=datetime.datetime(2026, 6, 18, 12),
                                     filename='fruiting.jpg', phase='fruiting', analysis_result=None))
        db.session.commit()
        result = self.client.get('/api/camera/history?start=2026-06-18T00:00&end=2026-06-20T23:59')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['fruiting_only'])
        self.assertIsNone(result.json['captures'][0]['analysis'])
        # Even existing legacy percentages and a supplied file must not trigger fruiting analysis.
        capture = CameraCapture(phase='fruiting', analysis_result='70%')
        self.assertIsNone(self.scope['_capture_analysis_value'](capture, 'nonexistent.jpg'))

    def test_mixed_gap_and_open_ended_windows(self):
        check = self.scope['_history_window_is_fruiting']
        start = datetime.datetime(2026, 6, 3)
        split = datetime.datetime(2026, 6, 12)
        end = datetime.datetime(2026, 6, 20)
        db.session.add(GrowthPhasePeriod(phase='colonization', start_time=start, end_time=split))
        db.session.add(GrowthPhasePeriod(phase='fruiting', start_time=split, end_time=None))
        db.session.commit()
        self.assertFalse(check(start, end))
        self.assertFalse(check(start - datetime.timedelta(days=1), end))
        self.assertTrue(check(split, end))
        self.assertFalse(check(start - datetime.timedelta(days=2), start - datetime.timedelta(days=1)))
        GrowthPhasePeriod.query.filter_by(phase='colonization').delete()
        db.session.add(GrowthPhasePeriod(phase='fruiting', start_time=start, end_time=split - datetime.timedelta(hours=1)))
        db.session.commit()
        self.assertFalse(check(start, end))


if __name__ == '__main__':
    unittest.main()
