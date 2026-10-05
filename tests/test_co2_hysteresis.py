"""CO2 hysteresis and pulse timing, without physical hardware."""
import ast
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class CO2HysteresisTests(unittest.TestCase):
    def setUp(self):
        self.settings = dict(co2_pulse_threshold_ppm=800, co2_hysteresis_ppm=100,
                             co2_pulse_duration_s=5, co2_pulse_cooldown_s=90,
                             co2_auto_vent_interval_min=0)
        self.clock = Mock()
        self.clock.monotonic.return_value = 100
        tree = ast.parse((ROOT / 'core/controller.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MushroomController')
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name in {'_control_air_quality', '_ensure_colonization_mode', '_ensure_stopped_mode'}]
        scope = dict(Config=types.SimpleNamespace(get=self.settings.get), time=self.clock,
                     RELAY_ID_FAN=1, RELAY_ID_HUMIDIFIER=2, RELAY_ID_LIGHT=3)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), 'controller.py', 'exec'), scope)
        self.controller = scope['MushroomController']()
        self.controller.relays = Mock()
        self.controller.relays.get_state.return_value = False
        self.controller.relays.camera_capture_active = False
        self.controller.response_monitor = Mock()
        self.controller._log_system_event = Mock()
        self.controller._co2_ventilation_demand = False
        self.controller._fan_pulse_end_at = 0
        self.controller._fan_next_allowed_pulse_at = 0
        self.controller._last_fan_impulse_at = 0

    def evaluate(self, co2, now):
        self.clock.monotonic.return_value = now
        self.controller._control_air_quality(co2)

    def test_dead_band_does_not_start_ventilation(self):
        self.evaluate(750, 100)
        self.evaluate(800, 101)
        self.controller.relays.set_state.assert_not_called()

    def test_demand_continues_to_lower_threshold_and_respects_cooldown(self):
        self.evaluate(801, 100)
        self.controller.relays.set_state.assert_called_once_with(1, True)
        self.evaluate(750, 105)
        self.controller.relays.set_state.assert_called_with(1, False)
        self.evaluate(750, 194)
        self.assertEqual(self.controller.relays.set_state.call_count, 2)
        self.evaluate(750, 195)
        self.controller.relays.set_state.assert_called_with(1, True)
        self.evaluate(700, 200)
        self.assertFalse(self.controller._co2_ventilation_demand)
        self.evaluate(750, 290)
        self.assertEqual(self.controller.relays.set_state.call_count, 4)

    def test_demand_clears_during_cooldown(self):
        self.evaluate(900, 100)
        self.evaluate(900, 105)
        self.evaluate(690, 150)
        self.evaluate(750, 195)
        self.assertEqual(self.controller.relays.set_state.call_count, 2)

    def test_zero_restores_single_threshold_behavior(self):
        self.settings['co2_hysteresis_ppm'] = 0
        self.evaluate(900, 100)
        self.evaluate(800, 105)
        self.evaluate(750, 195)
        self.assertFalse(self.controller._co2_ventilation_demand)
        self.assertEqual(self.controller.relays.set_state.call_count, 2)

    def test_auto_ventilation_is_independent(self):
        self.settings['co2_auto_vent_interval_min'] = 30
        self.evaluate(500, 1800)
        self.controller.relays.set_state.assert_called_once_with(1, True)

    def test_phase_changes_clear_demand(self):
        for method in ('_ensure_colonization_mode', '_ensure_stopped_mode'):
            self.controller._co2_ventilation_demand = True
            getattr(self.controller, method)()
            self.assertFalse(self.controller._co2_ventilation_demand)

    def test_setting_validation(self):
        tree = ast.parse((ROOT / 'config.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Config')
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name in {'set', 'get_description'}]
        model = Mock(side_effect=lambda **values: types.SimpleNamespace(**values))
        model.query.get.return_value = None
        database = Mock()
        scope = dict(Setting=model, db=database, SETTING_DESCRIPTIONS={})
        exec(compile(ast.Module(body=[cls], type_ignores=[]), 'config.py', 'exec'), scope)
        config = scope['Config']
        for invalid in (-1, 2.5, 'oops', None, 'nan', 'inf'):
            with self.assertRaises(ValueError):
                config.set('co2_hysteresis_ppm', invalid)
        database.session.add.assert_not_called()
        for valid in (0, 100, '50'):
            config.set('co2_hysteresis_ppm', valid)
            self.assertEqual(database.session.add.call_args.args[0].value, str(valid))


if __name__ == '__main__':
    unittest.main()
