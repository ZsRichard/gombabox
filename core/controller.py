import logging
import datetime
import os
from config import Config
from models import Measurement, SystemLog, CameraCapture
from core.vision import ImageAnalyzer

# --- KONSTANSOK (Hogy ne legyenek "mágikus számok" a kódban) ---
RELAY_ID_FAN = 1        # Ventilátor
RELAY_ID_HUMIDIFIER = 2 # Párásító
RELAY_ID_LIGHT = 3      # LED Világítás

# Konstans a CO2 hiszterézishez (mikor kapcsoljon ki a venti)
CO2_OFFSET_OFF = 200    # ppm

logger = logging.getLogger(__name__)

class MushroomController:
    """
    Az alkalmazás agya.
    Felelőssége: A beérkező adatok (szenzor, kamera) alapján döntéseket hozni
    és utasítani a beavatkozókat (relék).
    
    Elvek:
    - SRP: Nem ő végzi a mérést vagy a fotózást, csak koordinálja azokat.
    - DIP: A drivereket interfészeken (vagy duck-typingon) keresztül kapja meg.
    """
    
    def __init__(self, sensor_driver, relay_driver, camera_driver, db_session):
        # Dependency Injection: Minden külső függőséget megkapunk
        self.sensors = sensor_driver
        self.relays = relay_driver
        self.camera = camera_driver
        self.db = db_session
        
        # Számlálók a ciklusok ütemezéséhez
        self.sensor_cycle_counter = 0  # Szenzor: percenként
        self.visual_cycle_counter = 0  # Vizuális: óránként
        
        logger.info("✅ MushroomController inicializálva.")

    def run_cycle(self):
        """
        Fő ciklus: szenzor mérések minden percben, vizuális ellenőrzés óránként.
        """
        # Szenzor ciklus: minden percben
        self.run_sensor_cycle()
        
        # Vizuális ellenőrzés: 60. percek után (óránként)
        self.visual_cycle_counter += 1
        if self.visual_cycle_counter >= 60:  # 60 perc után
            self.run_visual_inspection()
            self.visual_cycle_counter = 0

    def run_sensor_cycle(self):
        """
        Környezetszabályozási ciklus (pl. percenként fut).
        Mér -> Ment -> Dönt -> Beavatkozik
        """
        try:
            # 1. Adatgyűjtés
            sensor_data = self.sensors.read_all()
            
            # 2. Mentés (Measurement)
            self._save_measurement(sensor_data)
            
            # 3. Kiértékelés és Beavatkozás (Logika kiszervezve metódusokba)
            self._control_humidity(sensor_data.get('hum', 0))
            self._control_light(sensor_data.get('light', 0))
            self._control_air_quality(sensor_data.get('co2', 0))
            
            # 4. Tranzakció lezárása
            self.db.session.commit()
            
        except Exception as e:
            logger.error(f"Hiba a szenzor ciklusban: {e}")
            self.db.session.rollback() # Ha hiba van, visszavonjuk az adatbázis műveletet

    def run_visual_inspection(self):
        """
        Vizuális ellenőrzési ciklus (pl. óránként fut).
        Fotóz -> Elemez -> Ment
        """
        logger.info("📸 Vizuális ellenőrzés indítása...")
        try:
            # 1. Képkészítés (A driver elvégzi a mentést a fájlrendszerbe)
            image_path = self.camera.capture_image()
            
            if not image_path:
                self._log_system_event("ERROR", "Nem sikerült képet készíteni a kamerával.")
                return

            # 2. Képelemzés (SRP: Külön osztály végzi a számítást)
            coverage_percent = ImageAnalyzer.calculate_mycelium_coverage(image_path)
            
            # 3. Eredmény mentése az adatbázisba
            self._save_camera_capture(image_path, coverage_percent)
            
            # Naplózás
            self._log_system_event("INFO", f"Kép elemezve. Átszőttség: {coverage_percent}%")
            self.db.session.commit()

        except Exception as e:
            logger.error(f"Hiba a vizuális ellenőrzés során: {e}")
            self.db.session.rollback()

    # --- PRIVÁT SEGÉDMETÓDUSOK (Clean Code: Kis, egyfeladatú függvények) ---

    def _control_humidity(self, current_humidity):
        """Párásító vezérlése hiszterézissel."""
        target_humidity = Config.get('target_humidity')
        hysteresis = Config.get('humidity_hysteresis')
        
        is_on = self.relays.get_state(RELAY_ID_HUMIDIFIER)
        
        # Bekapcsolás, ha túl száraz
        if current_humidity < (target_humidity - hysteresis):
            if not is_on:
                self.relays.set_state(RELAY_ID_HUMIDIFIER, True)
                self._log_system_event("INFO", f"Párásító BE (Mért: {current_humidity}%)")
        
        # Kikapcsolás, ha elérte a célt
        elif current_humidity > target_humidity:
            if is_on:
                self.relays.set_state(RELAY_ID_HUMIDIFIER, False)
                self._log_system_event("INFO", f"Párásító KI (Mért: {current_humidity}%)")

    def _control_light(self, current_lux):
        """Világítás vezérlése időzítő alapján."""
        start_hour = int(Config.get('light_on_hour'))
        end_hour = int(Config.get('light_off_hour'))
        
        now = datetime.datetime.now()
        current_hour = now.hour
        
        is_on = self.relays.get_state(RELAY_ID_LIGHT)
        
        # Logika: A megadott intervallumban kell világítani
        should_be_on = start_hour <= current_hour < end_hour

        if should_be_on and not is_on:
            self.relays.set_state(RELAY_ID_LIGHT, True)
            self._log_system_event("INFO", f"Világítás BE (Idő: {current_hour}:00)")
            
        elif not should_be_on and is_on:
            self.relays.set_state(RELAY_ID_LIGHT, False)
            self._log_system_event("INFO", f"Világítás KI (Idő: {current_hour}:00)")

    def _control_air_quality(self, current_co2):
        """Ventilátor vezérlése CO2 szint alapján."""
        co2_limit = Config.get('co2_limit')
        
        is_on = self.relays.get_state(RELAY_ID_FAN)

        # Bekapcsolás, ha rossz a levegő
        if current_co2 > co2_limit:
            if not is_on:
                self.relays.set_state(RELAY_ID_FAN, True)
                self._log_system_event("WARNING", f"Szellőzés BE (CO2: {current_co2} ppm)")
        
        # Kikapcsolás, ha a levegő tisztult (hiszterézis: limit - 200)
        elif current_co2 < (co2_limit - CO2_OFFSET_OFF):
            if is_on:
                self.relays.set_state(RELAY_ID_FAN, False)
                self._log_system_event("INFO", f"Szellőzés KI (CO2: {current_co2} ppm)")

    def _save_measurement(self, data):
        """Szenzoradatok perzisztálása."""
        measurement = Measurement(
            temperature=data.get('temp', 0.0),
            humidity=data.get('hum', 0.0),
            pressure=data.get('press', 0.0),
            co2=data.get('co2', 0),
            light=data.get('light', 0)
        )
        self.db.session.add(measurement)

    def _save_camera_capture(self, filepath, coverage):
        """Kép metaadatainak mentése."""
        filename = os.path.basename(filepath)
        capture = CameraCapture(
            filename=filename,
            analysis_result=f"{coverage}%" # Opcionálisan tárolhatnánk float-ként is
        )
        self.db.session.add(capture)

    def _log_system_event(self, level, message):
        """Rendszer esemény naplózása az adatbázisba."""
        log_entry = SystemLog(level=level, message=message)
        self.db.session.add(log_entry)
        # Konzolra is kiírjuk fejlesztéshez
        print(f"[{level}] {message}")