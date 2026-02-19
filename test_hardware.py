import time
import logging
import sys

# Konfiguráljuk a logolást, hogy lássuk a kimenetet
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("HardwareTest")

print("🚀 HARDVER DIAGNOSZTIKA INDÍTÁSA...")
print("-------------------------------------")

try:
    # 1. RELÉ TESZT
    print("\n[1/3] 🔌 Relék tesztelése...")
    from drivers.relays import RealRelayDriver
    relays = RealRelayDriver()
    
    # Minden relét végigkapcsolunk
    test_sequence = [
        (1, "Ventilátor"),
        (2, "Párásító"),
        (3, "Világítás")
    ]
    
    for relay_id, name in test_sequence:
        print(f"   -> {name} BEKAPCSOLÁSA...")
        relays.set_state(relay_id, True)
        time.sleep(2) # Hagyjuk menni 2 másodpercig
        
        print(f"   -> {name} KIKAPCSOLÁSA...")
        relays.set_state(relay_id, False)
        time.sleep(0.5)
    
    print("✅ Relé teszt KÉSZ.")

except Exception as e:
    print(f"❌ RELÉ HIBA: {e}")
    print("Ellenőrizd: GPIO bekötés, tápellátás, gpiozero telepítés.")


try:
    # 2. SZENZOR TESZT
    print("\n[2/3] 🌡️ Szenzorok tesztelése (5 mérés)...")
    from drivers.sensors import RealSensorDriver
    sensors = RealSensorDriver()
    
    for i in range(5):
        data = sensors.read_all()
        print(f"   Mérés #{i+1}: "
              f"Hőm: {data['temp']}°C | "
              f"Pára: {data['hum']}% | "
              f"Fény: {data['light']} lux | "
              f"CO2: {data['co2']} ppm")
        time.sleep(1)
        
    print("✅ Szenzor teszt KÉSZ.")

except Exception as e:
    print(f"❌ SZENZOR HIBA: {e}")
    print("Ellenőrizd: I2C engedélyezve? Serial console kikapcsolva? (raspi-config)")


try:
    # 3. KAMERA TESZT
    print("\n[3/3] 📸 Kamera tesztelése...")
    from drivers.camera import RealCameraDriver
    camera = RealCameraDriver()
    
    path = camera.capture_image()
    if path:
        print(f"✅ Kép sikeresen mentve ide: {path}")
    else:
        print("❌ Kép készítése sikertelen (None visszatérés).")

except Exception as e:
    print(f"❌ KAMERA HIBA: {e}")
    print("Ellenőrizd: Kamera szalagkábel, engedélyezés.")

print("\n-------------------------------------")
print("🏁 DIAGNOSZTIKA BEFEJEZŐDÖTT.")