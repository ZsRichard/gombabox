import logging
import datetime
import os
import time
from config import Config
from models import Measurement, SystemLog, CameraCapture
from core.vision import ImageAnalyzer

# --- CONSTANTS (To avoid "magic numbers" in code) ---
RELAY_ID_FAN = 1        # Fan
RELAY_ID_HUMIDIFIER = 2 # Humidifier
RELAY_ID_LIGHT = 3      # LED Light

# Camera focus time (milliseconds to wait for auto-focus before capture)
# Must match rpicam-still -t timeout value
# Increased to 5000ms for more reliable focus before capture
CAMERA_FOCUS_TIME_MS = 5000  # milliseconds
CAMERA_FOCUS_TIME_S = CAMERA_FOCUS_TIME_MS / 1000.0  # converted to seconds

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
        
        # Time-based scheduling state
        self._last_visual_inspection_at = time.monotonic()

        # Fan impulse control state
        self._fan_next_allowed_pulse_at = 0.0
        self._last_fan_impulse_at = time.monotonic()

        # Humidifier impulse control state
        self._humidifier_next_allowed_pulse_at = 0.0
        
        logger.info("MushroomController initialized.")

    def run_cycle(self):
        """
        Main cycle: sensor measurements and time-based visual inspection.
        """
        # Sensor cycle
        self.run_sensor_cycle()

        # Visual inspection uses real elapsed time in minutes, independent of loop speed.
        camera_interval_minutes = int(Config.get('camera_interval'))
        camera_interval_seconds = max(1, camera_interval_minutes) * 60
        now = time.monotonic()
        if (now - self._last_visual_inspection_at) >= camera_interval_seconds:
            self.run_visual_inspection()
            self._last_visual_inspection_at = time.monotonic()

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
            phase = self._get_growth_phase()
            if phase == 'colonization':
                self._ensure_colonization_mode()
            else:
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
            light_was_on = self._prepare_camera_light()
            try:
                image_path = self.camera.capture_image()
            finally:
                self._restore_camera_light(light_was_on)
            
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
        """Control humidifier with event-based pulses and cooldown."""
        target_humidity = Config.get('target_humidity')
        pulse_duration_s = int(Config.get('humidity_pulse_duration_s'))
        cooldown_s = int(Config.get('humidity_pulse_cooldown_s'))

        now = time.monotonic()
        if now < self._humidifier_next_allowed_pulse_at:
            return

        if current_humidity >= target_humidity:
            return

        self.relays.set_state(RELAY_ID_HUMIDIFIER, True)
        self._log_system_event(
            "INFO",
            f"Humidifier impulse ON for {pulse_duration_s}s (Measured: {current_humidity}%, target: {target_humidity}%)"
        )

        # Keep humidifier ON for fixed pulse duration regardless of immediate sensor fluctuation.
        time.sleep(pulse_duration_s)

        self.relays.set_state(RELAY_ID_HUMIDIFIER, False)
        self._log_system_event(
            "INFO",
            f"Humidifier impulse OFF. Cooldown active for {cooldown_s}s"
        )

        self._humidifier_next_allowed_pulse_at = time.monotonic() + cooldown_s

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
        """Control ventilation with event-based CO2 impulses and cooldown."""
        threshold_ppm = int(Config.get('co2_pulse_threshold_ppm'))
        pulse_duration_s = int(Config.get('co2_pulse_duration_s'))
        cooldown_s = int(Config.get('co2_pulse_cooldown_s'))
        auto_interval_s = int(Config.get('co2_auto_vent_interval_s'))

        now = time.monotonic()

        # During cooldown we suppress new ventilation impulses.
        if now < self._fan_next_allowed_pulse_at:
            return

        should_pulse = False
        pulse_reason = ""

        if current_co2 > threshold_ppm:
            should_pulse = True
            pulse_reason = f"CO2 trigger (CO2: {current_co2} ppm > {threshold_ppm} ppm)"
        elif auto_interval_s > 0 and (now - self._last_fan_impulse_at) >= auto_interval_s:
            should_pulse = True
            pulse_reason = (
                f"Automatic interval trigger ({auto_interval_s}s elapsed without ventilation)"
            )

        if not should_pulse:
            return

        self.relays.set_state(RELAY_ID_FAN, True)
        self._log_system_event(
            "INFO",
            f"Ventilation impulse ON for {pulse_duration_s}s - {pulse_reason}"
        )

        # Keep fan on for a fixed pulse duration, regardless of subsequent sensor values.
        time.sleep(pulse_duration_s)

        self.relays.set_state(RELAY_ID_FAN, False)
        self._log_system_event(
            "INFO",
            f"Ventilation impulse OFF. Cooldown active for {cooldown_s}s"
        )

        end_time = time.monotonic()
        self._last_fan_impulse_at = end_time
        self._fan_next_allowed_pulse_at = end_time + cooldown_s

    def _get_growth_phase(self):
        phase = Config.get('growth_phase')
        if not phase:
            return 'fruiting'
        return str(phase).strip().lower()

    def _ensure_colonization_mode(self):
        """Disable climate control and daily light during colonization."""
        if self.relays.get_state(RELAY_ID_FAN):
            self.relays.set_state(RELAY_ID_FAN, False)
            self._log_system_event("INFO", "Ventilation OFF (Colonization phase)")

        if self.relays.get_state(RELAY_ID_HUMIDIFIER):
            self.relays.set_state(RELAY_ID_HUMIDIFIER, False)
            self._log_system_event("INFO", "Humidifier OFF (Colonization phase)")

        if self.relays.get_state(RELAY_ID_LIGHT):
            self.relays.set_state(RELAY_ID_LIGHT, False)
            self._log_system_event("INFO", "Light OFF (Colonization phase)")

    def _prepare_camera_light(self):
        """Turn on LED and wait for camera to focus before capture.
        
        Ensures proper LED synchronization with camera focus time:
        - LED turns on to stabilize exposure
        - Waits for the longer of lead time or focus time
        - Returns previous light state for restoration after capture
        """
        lead_seconds = Config.get('camera_light_lead_seconds')
        try:
            lead_seconds = float(lead_seconds)
        except (TypeError, ValueError):
            lead_seconds = 0

        was_on = self.relays.get_state(RELAY_ID_LIGHT)

        if not was_on:
            self.relays.set_state(RELAY_ID_LIGHT, True)
            self._log_system_event("INFO", "Camera light ON for capture")

        # Ensure we wait long enough for both LED stabilization and camera auto-focus
        total_wait_seconds = max(lead_seconds, CAMERA_FOCUS_TIME_S)
        if total_wait_seconds > 0:
            self._log_system_event("INFO", f"Waiting {total_wait_seconds:.1f}s for LED stabilization and camera focus")
            time.sleep(total_wait_seconds)

        return was_on

    def _restore_camera_light(self, was_on):
        """Restore LED to previous state after capture."""
        if not was_on:
            self.relays.set_state(RELAY_ID_LIGHT, False)
            self._log_system_event("INFO", "Camera light OFF after capture")

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