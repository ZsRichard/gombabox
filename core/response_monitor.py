"""Passive response heuristics; no actuator writes. Thresholds need field validation."""
import math
import statistics
import threading
import time


class ResponseMonitor:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        with self.lock:
            self.trials, self.alerts = {}, {}
            self.target_samples = {'humidity': [], 'co2': []}
            self.latest = None
            self.light_since, self.light_samples = None, []
            self.last_sample = None

    @staticmethod
    def valid(value, kind):
        return (type(value) in (int, float) and math.isfinite(value)
                and (0 <= value <= 100 if kind == 'humidity' else value > 0 if kind == 'co2' else value >= 0))

    def pulse(self, kind, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.latest is None or now - self.last_sample > self.max_gap:
                return
            value = self.latest.get('hum' if kind == 'humidity' else 'co2')
            if not self.valid(value, kind):
                return
            target = self.targets[kind]
            if (kind == 'humidity' and value >= target) or (kind == 'co2' and value <= target):
                return
            trial = self.trials.setdefault(kind, dict(start=now, baseline=value, target=target, pulses=0, samples=[]))
            trial['pulses'] += 1

    def sample(self, data, phase, light_on, camera_active, humidity_target,
               co2_target, interval=60, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            targets = {'humidity': humidity_target, 'co2': co2_target}
            gap = max(180, interval * 3)
            if phase != 'fruiting':
                self.reset()
                return
            if (self.last_sample is not None and now - self.last_sample > gap) or (self.latest is not None and self.targets != targets):
                self.reset()
            self.last_sample, self.max_gap, self.targets = now, gap, targets
            self.latest = dict(data)
            for kind, field in [('humidity', 'hum'), ('co2', 'co2')]:
                value = data.get(field)
                if not self.valid(value, kind):
                    self.target_samples[kind] = []
                    self.trials.pop(kind, None)
                    self.alerts.pop(kind, None)
                    continue
                self.target_samples[kind] = (self.target_samples[kind] + [value])[-3:]
                if len(self.target_samples[kind]) == 3:
                    target_met = all(v >= targets[kind] for v in self.target_samples[kind]) if kind == 'humidity' else all(v <= targets[kind] for v in self.target_samples[kind])
                    if target_met:
                        self.alerts.pop(kind, None)
                trial = self.trials.get(kind)
                if not trial:
                    continue
                trial['samples'] = (trial['samples'] + [value])[-3:]
                if now - trial['start'] < 600:
                    continue
                if trial['pulses'] < 2 or len(trial['samples']) < 3:
                    if now - trial['start'] > max(1200, interval * 6):
                        self.trials.pop(kind, None)
                    continue
                value = statistics.median(trial['samples'])
                ok = (value >= trial['target'] or value - trial['baseline'] >= 2) if kind == 'humidity' else (value <= trial['target'] or trial['baseline'] - value >= 50)
                if ok:
                    self.alerts.pop(kind, None)
                else:
                    name, advice, unit = ('Párásítás', 'Ellenőrizd a víztartályt, a párásítót és a szenzor elhelyezését.', '%') if kind == 'humidity' else ('Szellőztetés', 'Ellenőrizd a ventilátort, a légutakat és a helyiség szellőzését.', 'ppm')
                    self.alerts[kind] = dict(key='response_' + kind, title=name + ': nem látszik megfelelő hatás', detail=f"{trial['pulses']} vezérlési impulzus után: {trial['baseline']:g} → {value:g} {unit}. Hibagyanú, nem bizonyított eszközhiba. {advice}")
                self.trials.pop(kind, None)
            lux = data.get('light')
            if not light_on or camera_active or not self.valid(lux, 'light'):
                self.light_since, self.light_samples = None, []
                self.alerts.pop('light', None)
            else:
                if self.light_since is None:
                    self.light_since = now
                self.light_samples = (self.light_samples + [lux])[-3:]
                if now - self.light_since >= 180 and len(self.light_samples) >= 3:
                    if statistics.median(self.light_samples) < 5:
                        self.alerts['light'] = dict(key='response_light', title='Világítás: túl kevés mért fény', detail='Tartós bekapcsolási parancs mellett 5 lux alatti fényérték mérhető. Ellenőrizd a lámpát és a fényszenzor takarását. Ez hibagyanú.')
                    else:
                        self.alerts.pop('light', None)

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.last_sample is None or now - self.last_sample > self.max_gap:
                return []
            return [dict(alert) for alert in self.alerts.values()]
