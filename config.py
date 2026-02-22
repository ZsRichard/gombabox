from models import db, Setting

# Default Configuration Values
# Used when system is freshly initialized or database is empty

DEFAULTS = {
    'target_temp': 24.0,        # Target temperature (°C)
    'temp_hysteresis': 1.0,     # Temperature tolerance (+/- °C)
    'target_humidity': 90.0,    # Target humidity (%)
    'humidity_hysteresis': 5.0, # Humidity tolerance (+/- %)
    'co2_limit': 1200,          # CO2 threshold for ventilation (ppm)
    'light_on_hour': 8,         # Light on time (hour)
    'light_off_hour': 20,       # Light off time (hour)
    'fan_cycle_on': 5,          # Fan cycle: duration on (minutes)
    'fan_cycle_off': 55,        # Fan cycle: duration off (minutes)
    'camera_interval': 60,      # Camera capture interval (minutes)
    'camera_light_lead_seconds': 5,  # LED lead time before capture (seconds)
    'growth_phase': 'fruiting'  # colonization | fruiting
}

class Config:
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
            new_setting = Setting(key=key, value=str(default_val))
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
            setting = Setting(key=key, value=str(value))
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