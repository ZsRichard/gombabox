"""Read-only monitoring rules. Ages are calculated in the server's time zone."""
import math


def evaluate_snapshot(snapshot, temp_margin=2, humidity_margin=10, co2_limit=1500):
    alerts = []
    def add(key, title, detail):
        alerts.append(dict(key=key, title=title, detail=detail))
    if snapshot['phase'] == 'stopped':
        return alerts
    if not snapshot['running']:
        add('automation', 'Az automatizálás nem fut', 'A szerver elérhető, de a háttérfolyamat áll.')
    age = snapshot['measurement_age_seconds']
    if age is None or age > max(180, snapshot['sample_interval_seconds'] * 3):
        add('stale', 'Nem érkezik friss mérés', 'Ellenőrizd a szenzorokat és az adatgyűjtést.')
    else:
        m = snapshot['measurement']
        for key, title, lower, upper, unit in (
            ('temp', 'Hőmérséklet', snapshot['target_temp'] - temp_margin, snapshot['target_temp'] + temp_margin, '°C'),
            ('hum', 'Páratartalom', max(0, snapshot['target_humidity'] - humidity_margin), min(100, snapshot['target_humidity'] + humidity_margin), '%'),
            ('co2', 'CO₂', 1, co2_limit, 'ppm'),
        ):
            value = m.get(key)
            invalid = not isinstance(value, (int, float)) or not math.isfinite(value)
            invalid = invalid or (key == 'co2' and value <= 0) or (key == 'hum' and not 0 <= value <= 100)
            if invalid:
                add('invalid_' + key, title + ': érvénytelen mérés', 'Lehetséges szenzor- vagy kommunikációs hiba.')
            elif value < lower or value > upper:
                add('range_' + key, title + (': túl alacsony' if value < lower else ': túl magas'), f'{value:g} {unit}; megengedett tartomány: {lower:g}–{upper:g} {unit}.')
        light = m.get('light')
        if not isinstance(light, (int, float)) or not math.isfinite(light) or light < 0:
            add('invalid_light', 'Fényszenzor: érvénytelen mérés', 'Lehetséges szenzor- vagy kommunikációs hiba. A nulla fényérték önmagában nem hiba.')
    camera_age = snapshot['capture_age_seconds']
    if camera_age is None or camera_age > max(300, snapshot['camera_interval_seconds'] * 2):
        add('camera', 'Késik az új kép', 'Több mint két képkészítési ciklus telt el új felvétel nélkül.')
    return alerts
