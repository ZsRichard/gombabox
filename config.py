from models import db, Setting

# 1. ALAPÉRTELMEZETT ÉRTÉKEK (Defaults)
# Ha friss a rendszer, vagy törlöd az adatbázist, ezek lépnek életbe.
DEFAULTS = {
    'target_temp': 24.0,       # Cél hőmérséklet (°C)
    'temp_hysteresis': 1.0,    # Hőfok tűréshatár (+/- 1°C)
    'target_humidity': 90.0,   # Cél páratartalom (%)
    'humidity_hysteresis': 5.0,# Pára tűréshatár (+/- 5%)
    'co2_limit': 1200,         # CO2 szint, ami felett szellőztetni kell (ppm)
    'light_on_hour': 8,        # Lámpa bekapcsolás (óra)
    'light_off_hour': 20,      # Lámpa kikapcsolás (óra)
    'fan_cycle_on': 5,         # Ventilátor ciklus: mennyi ideig megy (perc)
    'fan_cycle_off': 55        # Ventilátor ciklus: mennyi ideig áll (perc)
}

class Config:
    @staticmethod
    def get(key):
        """
        Lekéri egy beállítás értékét.
        Ha nincs az adatbázisban, visszaadja a DEFAULTS-ból és el is menti.
        Automatikusan felismeri a típust (int, float, str).
        """
        # 1. Próbáljuk lekérni az adatbázisból
        setting = Setting.query.get(key)

        if setting:
            return Config._cast_value(setting.value, key)
        
        # 2. Ha nincs, keressük a DEFAULTS-ban
        if key in DEFAULTS:
            default_val = DEFAULTS[key]
            # El is mentjük, hogy legközelebb meglegyen (Self-healing)
            new_setting = Setting(key=key, value=str(default_val))
            db.session.add(new_setting)
            db.session.commit()
            return default_val
        
        return None # Ha sehol nincs (programozói hiba)

    @staticmethod
    def set(key, value):
        """Beállít egy értéket és elmenti az adatbázisba."""
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
        Segédfüggvény: String -> Float/Int konverzió.
        A DEFAULTS alapján találja ki, milyen típusnak kellene lennie.
        """
        if key not in DEFAULTS:
            return value_str # Ha nem ismerjük, marad szöveg
            
        default_type = type(DEFAULTS[key])
        
        try:
            if default_type == int:
                return int(float(value_str)) # "23.0" -> 23
            elif default_type == float:
                return float(value_str)
            elif default_type == bool:
                return value_str.lower() == 'true'
        except:
            return value_str # Ha hiba van, marad szöveg
            
        return value_str