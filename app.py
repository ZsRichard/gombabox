# app.py RÉSZLET (A background_loop függvény cseréje)

# Importok
from drivers.relays import MockRelayDriver, RealRelayDriver
from drivers.sensors import MockSensorDriver, RealSensorDriver
from core.controller import MushroomController
from models import db # és a többi...

# --- KONFIGURÁCIÓ ---
# Ha távol vagy, ez legyen True!
USE_MOCK_HARDWARE = True 

def background_loop():
    """Ez fut a háttérben."""
    print("🚀 Háttérszál indítása...")
    
    with app.app_context():
        # 1. Driverek kiválasztása (Dependency Injection) [cite: 746]
        if USE_MOCK_HARDWARE:
            print("⚠️ SZIMULÁCIÓS MÓD AKTÍV")
            sensors = MockSensorDriver()
            relays = MockRelayDriver()
        else:
            print("⚡ ÉLES ÜZEMMÓD")
            sensors = RealSensorDriver()
            relays = RealRelayDriver()

        # 2. Controller létrehozása (injektáljuk a db session-t is)
        controller = MushroomController(sensors, relays, db.session)

        # 3. Végtelen ciklus
        while True:
            try:
                # Egyetlen hívás végzi a teljes logikát!
                controller.run_cycle()
            except Exception as e:
                print(f"🔥 KRITIKUS HIBA: {e}")
            
            # Várakozás (pl. 1 perc)
            time.sleep(60)