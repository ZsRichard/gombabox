import random
import logging
import serial
import board
import busio

# Hardveres könyvtárak importálása biztonságosan
try:
    from adafruit_bme280.basic import Adafruit_BME280_I2C
    from adafruit_bh1750 import BH1750
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
            logger.warning("⚠️ I2C könyvtárak nem elérhetők. Fallback MockSensorDriver-re.")
            self.mock = MockSensorDriver()
            self.is_mock = True
            return
        
        self.is_mock = False
        try:
            # I2C busz inicializálása
            self.i2c = busio.I2C(board.SCL, board.SDA)
            
            # BME280 csatlakoztatása
            self.bme = Adafruit_BME280_I2C(self.i2c, address=0x76)
            
            # BH1750 (Fényszenzor) csatlakoztatása
            self.light_sensor = BH1750(self.i2c, address=0x23)
            
            logger.info("✅ I2C szenzorok (BME280, BH1750) csatlakoztatva.")
        except Exception as e:
            logger.error(f"I2C Hiba: {e}")
            raise e

        # 2. Serial (MH-Z19C) - opcionális
        try:
            self.ser = serial.Serial('/dev/serial0', 9600, timeout=1)
            logger.info("✅ Soros port (MH-Z19C) megnyitva.")
        except Exception as e:
            logger.warning(f"Serial Hiba: {e}")
            self.ser = None

    def _read_mhz19(self):
        """MH-Z19C CO2 olvasás nyers bájtokkal."""
        if not self.ser: return 0
        try:
            # Parancs: Olvass CO2 koncentrációt
            command = b"\xff\x01\x86\x00\x00\x00\x00\x00\x79"
            self.ser.write(command)
            res = self.ser.read(9)
            if len(res) == 9 and res[0] == 0xff and res[1] == 0x86:
                return res[2] * 256 + res[3]
        except Exception as e:
            logger.error(f"CO2 olvasási hiba: {e}")
        return 0

    def read_all(self):
        # Ha mock módban vagyunk, delegálj
        if self.is_mock:
            return self.mock.read_all()
            
        # Valós adat olvasása
        return {
            'temp': round(self.bme.temperature, 1),
            'hum': round(self.bme.humidity, 1),
            'press': round(self.bme.pressure, 1),
            'co2': self._read_mhz19(),  # MH-Z19C soros portról
            'light': int(self.light_sensor.lux)
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