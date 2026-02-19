import logging
import datetime
import os
from config import Config
from models import Measurement, SystemLog, CameraCapture
from core.vision import ImageAnalyzer

# --- CONSTANTS (To avoid "magic numbers" in code) ---
RELAY_ID_FAN = 1        # Fan
RELAY_ID_HUMIDIFIER = 2 # Humidifier
RELAY_ID_LIGHT = 3      # LED Light

# Constant for CO2 hysteresis (when to turn off ventilation)
CO2_OFFSET_OFF = 200    # ppm

logger = logging.getLogger(__name__)

class MushroomController:
    """
    Mushroom growing controller - main application logic.
    
    Responsibilities: Coordinate sensor data, make control decisions,
    actuate hardware through relays.
    
    Principles:
    - SRP: Delegates measurement/photography to drivers
    - DIP: Depends on driver interfaces, not concrete implementations
    """
    
    def __init__(self, sensor_driver, relay_driver, camera_driver, db_session):
        # Dependency Injection: all external dependencies received
        self.sensors = sensor_driver
        self.relays = relay_driver
        self.camera = camera_driver
        self.db = db_session
        
        # Counters for cycle scheduling
        self.sensor_cycle_counter = 0  # Sensor: every minute
        self.visual_cycle_counter = 0  # Visual: every hour
        
        logger.info("MushroomController initialized.")

    def run_cycle(self):
        """
        Main cycle: sensor measurements every minute, visual inspection hourly.
        """
        # Sensor cycle: every minute
        self.run_sensor_cycle()
        
        # Visual inspection: after 60 minutes (hourly)
        self.visual_cycle_counter += 1
        if self.visual_cycle_counter >= 60:  # 60 minutes later
            self.run_visual_inspection()
            self.visual_cycle_counter = 0

    def run_sensor_cycle(self):
        """
        Environment control cycle (e.g., runs every minute).
        Measure -> Save -> Decide -> Actuate (relays)
        """
        try:
            # 1. Data collection
            sensor_data = self.sensors.read_all()
            
            # 2. Save (Measurement)
            self._save_measurement(sensor_data)
            
            # 3. Evaluate and Actuate (Logic delegated to separate methods)
            self._control_humidity(sensor_data.get('hum', 0))
            self._control_light(sensor_data.get('light', 0))
            self._control_air_quality(sensor_data.get('co2', 0))
            
            # 4. Commit transaction
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Error in sensor cycle: {e}")
            self.db.rollback()  # If error, rollback database changes

    def run_visual_inspection(self):
        """
        Visual inspection cycle (e.g., runs hourly).
        Photograph -> Analyze -> Save
        """
        logger.info("Visual inspection started.")
        try:
            # 1. Image capture (Driver saves to filesystem)
            image_path = self.camera.capture_image()
            
            if not image_path:
                self._log_system_event("ERROR", "Failed to capture image from camera.")
                return

            # 2. Image analysis (SRP: Separate class does the calculation)
            coverage_percent = ImageAnalyzer.calculate_mycelium_coverage(image_path)
            
            # 3. Save result to database
            self._save_camera_capture(image_path, coverage_percent)
            
            # Logging
            self._log_system_event("INFO", f"Image analyzed. Coverage: {coverage_percent}%")
            self.db.commit()

        except Exception as e:
            logger.error(f"Error during visual inspection: {e}")
            self.db.rollback()

    # --- Private Helper Methods (Small, single-purpose functions - Clean Code) ---

    def _control_humidity(self, current_humidity):
        """Control humidifier with hysteresis."""
        target_humidity = Config.get('target_humidity')
        hysteresis = Config.get('humidity_hysteresis')
        
        is_on = self.relays.get_state(RELAY_ID_HUMIDIFIER)
        
        # Turn on if too dry
        if current_humidity < (target_humidity - hysteresis):
            if not is_on:
                self.relays.set_state(RELAY_ID_HUMIDIFIER, True)
                self._log_system_event("INFO", f"Humidifier ON (Measured: {current_humidity}%)")
        
        # Turn off when target is reached
        elif current_humidity > target_humidity:
            if is_on:
                self.relays.set_state(RELAY_ID_HUMIDIFIER, False)
                self._log_system_event("INFO", f"Humidifier OFF (Measured: {current_humidity}%)")

    def _control_light(self, current_lux):
        """Control lighting based on timer."""
        start_hour = int(Config.get('light_on_hour'))
        end_hour = int(Config.get('light_off_hour'))
        
        now = datetime.datetime.now()
        current_hour = now.hour
        
        is_on = self.relays.get_state(RELAY_ID_LIGHT)
        
        # Logic: Light should be on in the specified interval
        should_be_on = start_hour <= current_hour < end_hour

        if should_be_on and not is_on:
            self.relays.set_state(RELAY_ID_LIGHT, True)
            self._log_system_event("INFO", f"Light ON (Time: {current_hour}:00)")
            
        elif not should_be_on and is_on:
            self.relays.set_state(RELAY_ID_LIGHT, False)
            self._log_system_event("INFO", f"Light OFF (Time: {current_hour}:00)")

    def _control_air_quality(self, current_co2):
        """Control ventilation based on CO2 level."""
        co2_limit = Config.get('co2_limit')
        
        is_on = self.relays.get_state(RELAY_ID_FAN)

        # Turn on if air quality is poor
        if current_co2 > co2_limit:
            if not is_on:
                self.relays.set_state(RELAY_ID_FAN, True)
                self._log_system_event("WARNING", f"Ventilation ON (CO2: {current_co2} ppm)")
        
        # Turn off if air quality improved (hysteresis: limit - 200)
        elif current_co2 < (co2_limit - CO2_OFFSET_OFF):
            if is_on:
                self.relays.set_state(RELAY_ID_FAN, False)
                self._log_system_event("INFO", f"Ventilation OFF (CO2: {current_co2} ppm)")

    def _save_measurement(self, data):
        """Persisting sensor data."""
        measurement = Measurement(
            temperature=data.get('temp', 0.0),
            humidity=data.get('hum', 0.0),
            pressure=data.get('press', 0.0),
            co2=data.get('co2', 0),
            light=data.get('light', 0)
        )
        self.db.add(measurement)

    def _save_camera_capture(self, filepath, coverage):
        """Save image metadata."""
        filename = os.path.basename(filepath)
        capture = CameraCapture(
            filename=filename,
            analysis_result=f"{coverage}%"  # Could optionally store as float
        )
        self.db.add(capture)

    def _log_system_event(self, level, message):
        """Log system events to the database."""
        log_entry = SystemLog(level=level, message=message)
        self.db.add(log_entry)
        # Also print to console for development
        print(f"[{level}] {message}")