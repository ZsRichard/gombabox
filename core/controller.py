import datetime
from config import Config
from models import Measurement, SystemLog

class MushroomController:
    """
    Az üzleti logika központja.
    Döntéseket hoz a szenzoradatok és a beállítások alapján.
    """
    
    def __init__(self, sensor_driver, relay_driver, db_session):
        # Dependency Injection: Nem itt hozzuk létre a drivereket, hanem megkapjuk őket.
        self.sensors = sensor_driver
        self.relays = relay_driver
        self.db = db_session
        print("✅ MushroomController elindult.")

    def run_cycle(self):
        """
        Ezt a metódust hívja majd a főprogram percenként (vagy sűrűbben).
        Ez egy teljes "gondolkodási ciklus".
        """
        # 1. MÉRÉS (Adatgyűjtés)
        try:
            data = self.sensors.read_all()
        except Exception as e:
            self._log("ERROR", f"Szenzor hiba: {e}")
            return # Ha nincs adat, nem tudunk dönteni

        # 2. MENTÉS AZ ADATBÁZISBA (Measurement)
        self._save_measurement(data)

        # 3. DÖNTÉSHOZATAL (Vezérlés)
        # Minden alrendszer külön metódust kap (SRP)
        self._control_humidity(data['hum'])
        self._control_light(data['light'])
        self._control_air(data['co2'])
        
        # A változtatásokat kommitoljuk az adatbázisba (Logok, Mérések)
        self.db.commit()

    def _control_humidity(self, current_hum):
        """Párásító vezérlése hiszterézissel."""
        target = Config.get('target_humidity')      # pl. 90.0
        hysteresis = Config.get('humidity_hysteresis') # pl. 5.0
        
        # RELÉ ID: 2 (Párásító)
        relay_id = 2
        is_on = self.relays.get_state(relay_id)

        if current_hum < (target - hysteresis):
            if not is_on:
                self.relays.set_state(relay_id, True)
                self._log("INFO", f"Párásító BE (Mért: {current_hum}%, Cél: {target}%)")
        
        elif current_hum > target:
            if is_on:
                self.relays.set_state(relay_id, False)
                self._log("INFO", f"Párásító KI (Mért: {current_hum}%, Cél: {target}%)")

    def _control_light(self, current_lux):
        """Világítás vezérlése időzítővel."""
        start_hour = int(Config.get('light_on_hour')) # pl. 8
        end_hour = int(Config.get('light_off_hour'))  # pl. 20
        
        now = datetime.datetime.now()
        current_hour = now.hour

        # RELÉ ID: 3 (LED Lámpa)
        relay_id = 3
        is_on = self.relays.get_state(relay_id)
        
        # Egyszerű logika: Ha a két óra között vagyunk -> BE
        should_be_on = start_hour <= current_hour < end_hour

        if should_be_on and not is_on:
            self.relays.set_state(relay_id, True)
            self._log("INFO", f"Világítás BE (Idő: {current_hour}:00)")
            
        elif not should_be_on and is_on:
            self.relays.set_state(relay_id, False)
            self._log("INFO", f"Világítás KI (Idő: {current_hour}:00)")

    def _control_air(self, current_co2):
        """Szellőztetés vezérlése CO2 szint alapján."""
        limit = Config.get('co2_limit') # pl. 1200 ppm
        
        # RELÉ ID: 1 (Ventilátor)
        relay_id = 1
        is_on = self.relays.get_state(relay_id)

        # Ha magas a CO2 -> Szellőztetünk
        if current_co2 > limit:
            if not is_on:
                self.relays.set_state(relay_id, True)
                self._log("WARNING", f"Szellőzés BE (CO2: {current_co2} ppm > {limit})")
        
        # Ha lement a szint (pl. 200 ppm-mel a limit alá), kikapcsoljuk
        elif current_co2 < (limit - 200):
            if is_on:
                self.relays.set_state(relay_id, False)
                self._log("INFO", f"Szellőzés KI (CO2: {current_co2} ppm helyreállt)")

    def _save_measurement(self, data):
        """Mérés mentése az adatbázisba."""
        # KISS: Nem bonyolítjuk, csak létrehozzuk az objektumot
        m = Measurement(
            temperature=data['temp'],
            humidity=data['hum'],
            pressure=data['press'],
            co2=data['co2'],
            light=data['light']
        )
        self.db.add(m)

    def _log(self, level, message):
        """Belső segédfüggvény naplózáshoz."""
        log_entry = SystemLog(level=level, message=message)
        self.db.add(log_entry)
        # Opcionálisan kiírjuk a konzolra is fejlesztéshez
        print(f"[{level}] {message}")