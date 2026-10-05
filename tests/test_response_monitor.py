import unittest
from core.response_monitor import ResponseMonitor


class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.m = ResponseMonitor()

    def sample(self, t, hum=60, co2=1200, light=0, phase='fruiting', on=False, camera=False):
        self.m.sample(dict(hum=hum, co2=co2, light=light), phase, on, camera, 87, 800, now=t)

    def run_window(self, hum=60, co2=1200):
        self.sample(0)
        self.m.pulse('humidity', 0)
        self.m.pulse('co2', 0)
        for t in range(60, 601, 60):
            self.sample(t, hum, co2)
            if t == 120:
                self.m.pulse('humidity', t)
                self.m.pulse('co2', t)

    def test_no_change_warns(self):
        self.run_window()
        self.assertEqual({a['key'] for a in self.m.snapshot(600)}, {'response_humidity', 'response_co2'})

    def test_response_no_warning(self):
        self.run_window(65, 1100)
        self.assertEqual(self.m.snapshot(600), [])

    def test_no_pulses_no_claim(self):
        for t in range(0, 1201, 60):
            self.sample(t)
        self.assertEqual(self.m.snapshot(1200), [])

    def test_gap_invalid_and_stopped(self):
        self.run_window()
        self.assertEqual(self.m.snapshot(1000), [])
        self.sample(1000)
        self.assertEqual(self.m.snapshot(1000), [])
        self.sample(1060, hum=None, co2=0)
        self.m.pulse('humidity', 1060)
        self.m.pulse('co2', 1060)
        self.assertEqual(self.m.trials, {})
        self.sample(1120, phase='stopped')
        self.assertEqual(self.m.snapshot(1120), [])

    def test_light_debounce_camera_and_recovery(self):
        for t in (0, 60, 120):
            self.sample(t, on=True)
        self.assertEqual(self.m.snapshot(120), [])
        self.sample(180, on=True)
        self.assertEqual(self.m.snapshot(180)[0]['key'], 'response_light')
        self.sample(240, on=True, camera=True)
        self.assertEqual(self.m.snapshot(240), [])
        for t in (300, 360, 420, 480):
            self.sample(t, on=True, light=100)
        self.assertEqual(self.m.snapshot(480), [])

    def test_low_co2_scheduled_fan_not_evaluated(self):
        self.sample(0, co2=500)
        self.m.pulse('co2', 0)
        self.assertEqual(self.m.trials, {})


if __name__ == '__main__':
    unittest.main()
