import random
import logging
import serial

# Import hardware libraries safely
try:
    import board
    import busio
    from adafruit_bme280.basic import Adafruit_BME280_I2C
    from adafruit_bh1750 import BH1750
    I2C_AVAILABLE = True
except ImportError:
    I2C_AVAILABLE = False

logger = logging.getLogger(__name__)

class SensorDriver:
    """Interface for measurements."""
    def read_all(self):
        """Return a dictionary: {'temp': 22.5, 'hum': 60, ...}"""
        raise NotImplementedError

class RealSensorDriver(SensorDriver):
    def __init__(self):
        if not I2C_AVAILABLE:
            logger.warning("I2C libraries not available. Falling back to MockSensorDriver.")
            self.mock = MockSensorDriver()
            self.is_mock = True
            return
        
        self.is_mock = False
        try:
            # Initialize I2C bus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            
            # Connect BME280
            self.bme = Adafruit_BME280_I2C(self.i2c, address=0x76)
            
            # Connect BH1750 (Light Sensor)
            self.light_sensor = BH1750(self.i2c, address=0x23)
            
            logger.info("I2C sensors (BME280, BH1750) connected.")
        except Exception as e:
            logger.error(f"I2C Error: {e}")
            raise e

        # 2. Serial (MH-Z19C) - optional
        try:
            self.ser = serial.Serial('/dev/serial0', 9600, timeout=1)
            logger.info("Serial port (MH-Z19C) opened.")
        except Exception as e:
            logger.warning(f"Serial error: {e}")
            self.ser = None

    def _read_mhz19(self):
        """MH-Z19C CO2 reading with raw bytes."""
        if not self.ser: return 0
        try:
            # Command: Read CO2 concentration
            command = b"\xff\x01\x86\x00\x00\x00\x00\x00\x79"
            self.ser.write(command)
            res = self.ser.read(9)
            if len(res) == 9 and res[0] == 0xff and res[1] == 0x86:
                return res[2] * 256 + res[3]
        except Exception as e:
            logger.error(f"CO2 read error: {e}")
        return 0

    def read_all(self):
        # If we're in mock mode, delegate to it
        if self.is_mock:
            return self.mock.read_all()
            
        # Read real data
        return {
            'temp': round(self.bme.temperature, 1),
            'hum': round(self.bme.humidity, 1),
            'press': round(self.bme.pressure, 1),
            'co2': self._read_mhz19(),  # MH-Z19C serial port
            'light': int(self.light_sensor.lux)
        }

class MockSensorDriver(SensorDriver):
    """Simulated data generation (Random Walk pattern)."""
    def __init__(self):
        logger.info("MockSensorDriver: Generating random data.")
        # Initial values
        self.data = {
            'temp': 24.0, 'hum': 80.0, 'press': 1013.0, 'co2': 800, 'light': 500
        }

    def read_all(self):
        # Slightly modify the previous value (Random Walk) so the graph looks realistic
        self.data['temp'] += random.uniform(-0.5, 0.5)
        self.data['hum'] += random.uniform(-2.0, 2.0)
        self.data['co2'] += random.randint(-50, 50)
        
        # Keep limits (don't go to -200 degrees)
        self.data['temp'] = max(15, min(35, self.data['temp']))
        self.data['hum'] = max(30, min(100, self.data['hum']))
        
        return self.data.copy()