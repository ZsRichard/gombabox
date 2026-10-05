"""Verify phase-specific capture behavior without touching real hardware."""
import ast
import logging
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, jsonify

ROOT = Path(__file__).resolve().parents[1]


class CapturePhaseTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = Mock()
        self.analyzer.calculate_mycelium_coverage.return_value = 42.5
        self.camera = Mock()
        self.camera.capture_image.return_value = '/tmp/capture.jpg'
        self.db = Mock()
        self.capture_model = lambda **kwargs: types.SimpleNamespace(**kwargs)

    def controller(self, phase):
        tree = ast.parse((ROOT / 'core/controller.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MushroomController')
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                    and node.name in {'run_visual_inspection', '_save_camera_capture'}]
        scope = dict(ImageAnalyzer=self.analyzer, CameraCapture=self.capture_model,
                     os=os, logger=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[cls], type_ignores=[]), 'controller.py', 'exec'), scope)
        controller = scope['MushroomController']()
        controller._get_growth_phase = lambda: phase
        controller.camera = self.camera
        controller.db = self.db
        controller._prepare_camera_light = Mock(return_value=False)
        controller._restore_camera_light = Mock()
        controller._log_system_event = Mock()
        return controller

    def test_scheduled_fruiting_capture_skips_analysis(self):
        self.controller('fruiting').run_visual_inspection()
        self.camera.capture_image.assert_called_once()
        self.analyzer.calculate_mycelium_coverage.assert_not_called()
        saved = self.db.add.call_args.args[0]
        self.assertEqual(saved.phase, 'fruiting')
        self.assertIsNone(saved.analysis_result)
        self.db.commit.assert_called_once()

    def test_scheduled_incubation_preserves_analysis(self):
        self.controller('colonization').run_visual_inspection()
        self.analyzer.calculate_mycelium_coverage.assert_called_once()
        self.assertEqual(self.db.add.call_args.args[0].analysis_result, '42.5%')

    def test_stopped_has_no_capture(self):
        self.controller('stopped').run_visual_inspection()
        self.camera.capture_image.assert_not_called()
        self.db.add.assert_not_called()

    def test_manual_capture_phase(self):
        for phase in ('fruiting', 'colonization', 'stopped'):
            with self.subTest(phase=phase):
                self.db.reset_mock()
                self.analyzer.reset_mock()
                app = Flask(__name__)
                config = Mock()
                config.get.side_effect = lambda key: phase if key == 'growth_phase' else 0
                camera_module = types.ModuleType('drivers.camera')
                camera_module.RealCameraDriver = camera_module.MockCameraDriver = lambda: self.camera
                vision_module = types.ModuleType('core.vision')
                vision_module.ImageAnalyzer = self.analyzer
                tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
                node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'capture_now')
                scope = dict(app=app, Config=config, jsonify=jsonify, USE_MOCK_HARDWARE=True,
                             relay_driver=Mock(), time=Mock(), CameraCapture=self.capture_model,
                             db=types.SimpleNamespace(session=self.db), logger=logging.getLogger(__name__))
                exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), scope)
                with patch.dict(sys.modules, {'drivers.camera': camera_module, 'core.vision': vision_module}):
                    response = app.test_client().post('/api/camera/capture')
                if phase == 'stopped':
                    self.assertEqual(response.status_code, 409)
                    self.db.add.assert_not_called()
                else:
                    self.assertEqual(response.status_code, 200)
                    saved = self.db.add.call_args.args[0]
                    if phase == 'fruiting':
                        self.assertIsNone(response.json['coverage'])
                        self.assertIsNone(saved.analysis_result)
                        self.analyzer.calculate_mycelium_coverage.assert_not_called()
                    else:
                        self.assertEqual(response.json['coverage'], 42.5)
                        self.assertEqual(saved.analysis_result, '42.5%')


if __name__ == '__main__':
    unittest.main()
