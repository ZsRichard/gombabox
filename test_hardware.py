import time
import logging
import sys

# Configure logging so we can see the output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("HardwareTest")

print("HARDWARE DIAGNOSTICS STARTING...")
print("-------------------------------------")

try:
    # 1. RELAY TEST
    print("\n[1/3] Testing relays...")
    from drivers.relays import RealRelayDriver
    relays = RealRelayDriver()
    
    # Test every relay
    test_sequence = [
        (1, "Fan"),
        (2, "Humidifier"),
        (3, "Light")
    ]
    
    for relay_id, name in test_sequence:
        print(f"   -> Turning ON {name}...")
        relays.set_state(relay_id, True)
        time.sleep(2) # Let it run for 2 seconds
        
        print(f"   -> Turning OFF {name}...")
        relays.set_state(relay_id, False)
        time.sleep(0.5)
    
    print("Relay test COMPLETED.")

except Exception as e:
    print(f"RELAY ERROR: {e}")
    print("Check: GPIO connection, power supply, gpiozero installation.")


try:
    # 2. SZENZOR TESZT
    print("\n[2/3] Testing sensors (5 measurements)...")
    from drivers.sensors import RealSensorDriver
    sensors = RealSensorDriver()
    
    for i in range(5):
        data = sensors.read_all()
        print(f"   Measurement #{i+1}: "
              f"Temp: {data['temp']}°C | "
              f"Humidity: {data['hum']}% | "
              f"Light: {data['light']} lux | "
              f"CO2: {data['co2']} ppm")
        time.sleep(1)
        
    print("Sensor test COMPLETED.")

except Exception as e:
    print(f"SENSOR ERROR: {e}")
    print("Check: I2C enabled? Serial console disabled? (raspi-config)")


try:
    # 3. KAMERA TESZT
    print("\n[3/3] Testing camera...")
    from drivers.camera import RealCameraDriver
    camera = RealCameraDriver()
    
    path = camera.capture_image()
    if path:
        print(f"Image successfully saved: {path}")
    else:
        print("Image capture failed (None returned).")

except Exception as e:
    print(f"CAMERA ERROR: {e}")
    print("Check: Camera ribbon cable, permissions.")

print("\n-------------------------------------")
print("DIAGNOSTICS COMPLETED.")