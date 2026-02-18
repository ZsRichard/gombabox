import random
import logging

# Hardveres könyvtárak importálása biztonságosan
try:
    import board
    import adafruit_bme280
    import adafruit_bh1750
    import adafruit_scd30
    I2C_AVAILABLE = True
except ImportError:
    I2C_AVAILABLE = False

logger = logging.getLogger(__name__)

class SensorDriver:
    """Interfész a mérésekhez."""
    def read_all(self):
        """Visszaad egy szótárat: {'temp': 22.5, 'hum': 60, ...}"""
        raise NotImplementedError

class RealSensorDriver(SensorDriver):
    def __init__(self):
        if not I2C_AVAILABLE:
            raise RuntimeError("I2C könyvtárak hiányoznak!")
        
        try:
            i2c = board.I2C()
            self.bme = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=0x76)
            self.scd = adafruit_scd30.SCD30(i2c)
            self.light = adafruit_bh1750.BH1750(i2c)
            logger.info("✅ RealSensorDriver: Szenzorok csatlakoztatva.")
        except Exception as e:
            logger.error(f"Hiba a szenzorok indításakor: {e}")
            # Itt lehetne retry logika, de KISS: ha nem megy, omoljon össze inicializáláskor
            raise e

    def read_all(self):
        # Valós adat olvasása
        # Megjegyzés: Az SCD30 lassú lehet, itt egyszerűsítünk
        return {
            'temp': round(self.bme.temperature, 1),
            'hum': round(self.bme.relative_humidity, 1),
            'press': round(self.bme.pressure, 1),
            'co2': int(self.scd.CO2) if self.scd.data_available else 0,
            'light': int(self.light.lux)
        }

class MockSensorDriver(SensorDriver):
    """Szimulált adatok generálása (Random Walk)."""
    def __init__(self):
        logger.info("⚠️ MockSensorDriver: Véletlenszerű adatokat generál.")
        # Kezdőértékek
        self.data = {
            'temp': 24.0, 'hum': 80.0, 'press': 1013.0, 'co2': 800, 'light': 500
        }

    def read_all(self):
        # Kicsit módosítjuk az előző értéket (Random Walk), hogy élethű legyen a grafikon
        self.data['temp'] += random.uniform(-0.5, 0.5)
        self.data['hum'] += random.uniform(-2.0, 2.0)
        self.data['co2'] += random.randint(-50, 50)
        
        # Határértékek betartása (ne legyen -200 fok)
        self.data['temp'] = max(15, min(35, self.data['temp']))
        self.data['hum'] = max(30, min(100, self.data['hum']))
        
        return self.data.copy()