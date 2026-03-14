from models import db, Setting

# Default Configuration Values
# Used when system is freshly initialized or database is empty

DEFAULTS = {
    'target_temp': 24.0,        # Target temperature (°C)
    'temp_hysteresis': 1.0,     # Temperature tolerance (+/- °C)
    'target_humidity': 90.0,    # Target humidity (%)
    'humidity_hysteresis': 3.0, # Humidity tolerance (+/- %)
    'humidity_pulse_duration_s': 20, # Humidifier ON pulse length (seconds)
    'humidity_pulse_cooldown_s': 60, # Delay after humidity pulse before next one (seconds)
    'co2_pulse_threshold_ppm': 800,  # CO2 threshold for impulse ventilation (ppm)
    'co2_pulse_duration_s': 5,        # Impulse ventilation ON time (seconds)
    'co2_pulse_cooldown_s': 90,       # Delay after impulse before allowing next one (seconds)
    'co2_auto_vent_interval_s': 1800, # Automatic ventilation interval when no impulse occurred (seconds)
    'light_on_hour': 8,         # Light on time (hour)
    'light_off_hour': 20,       # Light off time (hour)
    'fan_cycle_on': 5,          # Fan cycle: duration on (minutes)
    'fan_cycle_off': 55,        # Fan cycle: duration off (minutes)
    'camera_interval': 60,      # Camera capture interval (minutes)
    'camera_light_lead_seconds': 0,  # LED lead time before capture (seconds), focus wait handled separately
    'service_cycle_interval_s': 60,  # Background control loop interval (seconds)
    'growth_phase': 'fruiting'  # colonization | fruiting
}

SETTING_DESCRIPTIONS = {
    'target_temp': 'Target temperature in C.',
    'temp_hysteresis': 'Temperature tolerance band.',
    'target_humidity': 'Target relative humidity percent.',
    'humidity_hysteresis': 'Humidity tolerance band.',
    'humidity_pulse_duration_s': 'Humidifier ON pulse in seconds.',
    'humidity_pulse_cooldown_s': 'Pause after humidifier pulse in seconds.',
    'co2_pulse_threshold_ppm': 'CO2 threshold for ventilation pulse.',
    'co2_pulse_duration_s': 'Ventilation ON pulse in seconds.',
    'co2_pulse_cooldown_s': 'Pause after ventilation pulse in seconds.',
    'co2_auto_vent_interval_s': 'Auto ventilation interval in seconds.',
    'light_on_hour': 'Daily light start hour (0-23).',
    'light_off_hour': 'Daily light stop hour (0-23).',
    'fan_cycle_on': 'Legacy fan cycle ON minutes.',
    'fan_cycle_off': 'Legacy fan cycle OFF minutes.',
    'camera_interval': 'Camera capture interval in minutes.',
    'camera_light_lead_seconds': 'LED lead time before capture in seconds.',
    'service_cycle_interval_s': 'Service control loop interval in seconds.',
    'growth_phase': 'Grow phase: colonization or fruiting.'
}

class Config:
    @staticmethod
    def get_description(key):
        """Return short human-readable description for a setting key."""
        return SETTING_DESCRIPTIONS.get(key)

    @staticmethod
    def ensure_descriptions():
        """Backfill missing descriptions for known settings."""
        changed = False
        for key, description in SETTING_DESCRIPTIONS.items():
            setting = Setting.query.get(key)
            if setting and not setting.description and description:
                setting.description = description
                changed = True

        if changed:
            db.session.commit()

    @staticmethod
    def get(key):
        """
        Get a setting value.
        If not in database, return from DEFAULTS and save it.
        Automatically recognizes type (int, float, str).
        """
        # 1. Try to retrieve from database
        setting = Setting.query.get(key)

        if setting:
            return Config._cast_value(setting.value, key)
        
        # 2. If not found, search in DEFAULTS
        if key in DEFAULTS:
            default_val = DEFAULTS[key]
            # Also save it so it's available next time (Self-healing)
            new_setting = Setting(
                key=key,
                value=str(default_val),
                description=Config.get_description(key)
            )
            db.session.add(new_setting)
            db.session.commit()
            return default_val
        
        return None  # If nowhere to be found (programmer error)

    @staticmethod
    def set(key, value):
        """Set a value and save to database."""
        setting = Setting.query.get(key)
        
        if setting:
            setting.value = str(value)
        else:
            setting = Setting(
                key=key,
                value=str(value),
                description=Config.get_description(key)
            )
            db.session.add(setting)
        
        db.session.commit()

    @staticmethod
    def _cast_value(value_str, key):
        """
        Helper function: String -> Float/Int conversion.
        Based on DEFAULTS, figure out what type it should be.
        """
        if key not in DEFAULTS:
            return value_str  # If unknown, stay as text
            
        default_type = type(DEFAULTS[key])
        
        try:
            if default_type == int:
                return int(float(value_str))  # "23.0" -> 23
            elif default_type == float:
                return float(value_str)
            elif default_type == bool:
                return value_str.lower() == 'true'
        except:
            return value_str  # If error, stay as text
            
        return value_str