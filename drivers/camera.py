# drivers/camera.py
import abc
import numpy as np
import os
import logging
import subprocess
from datetime import datetime
from core.constants import CAPTURE_DIRECTORY

logger = logging.getLogger(__name__)

class CameraDriver(abc.ABC):
    """
    Absztrakt interfész (DIP).
    A magas szintű modulok (Controller) ettől függenek, nem a RealCameraDriver-től.
    """
    @abc.abstractmethod
    def capture_image(self) -> str:
        """Képet készít és visszaadja a fájl elérési útját."""
        pass

class RealCameraDriver(CameraDriver):
    """
    Raspberry Pi Camera v3 (IMX708) implementáció rpicam-ot használva.
    """
    def __init__(self):
        # Ellenőrizze, hogy az rpicam-still elérhető-e
        try:
            result = subprocess.run(['which', 'rpicam-still'], 
                                  capture_output=True, timeout=5)
            self.rpicam_available = result.returncode == 0
            
            if self.rpicam_available:
                logger.info("✅ rpicam-still csatlakoztatva.")
            else:
                logger.warning("⚠️ rpicam-still nem érhető el. Fallback MockCameraDriver-re.")
                self.mock = MockCameraDriver()
        except Exception as e:
            logger.warning(f"⚠️ rpicam ellenőrzése sikertelen: {e}")
            self.rpicam_available = False
            self.mock = MockCameraDriver()
    
    def capture_image(self) -> str:
        # Ha rpicam nem érhető el, Mock
        if not self.rpicam_available:
            return self.mock.capture_image()
            
        # Biztosítjuk, hogy a könyvtár létezik
        os.makedirs(CAPTURE_DIRECTORY, exist_ok=True)
        
        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(CAPTURE_DIRECTORY, filename)
        
        try:
            # rpicam-still parancs: készít egy képet 1920x1080 felbontáson
            cmd = [
                'rpicam-still',
                '-o', filepath,
                '--width', '1920',
                '--height', '1080',
                '-t', '1000'  # timeout: 1000ms
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            
            if result.returncode == 0 and os.path.exists(filepath):
                logger.info(f"✅ Kép sikeresen mentve: {filepath}")
                return filepath
            else:
                logger.error(f"❌ rpicam hiba: {result.stderr.decode()}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("❌ rpicam timeout")
            return None
        except Exception as e:
            logger.error(f"❌ Kamera hiba: {e}")
            return None

class MockCameraDriver(CameraDriver):
    """
    Teszteléshez (Mock).
    Generál egy fekete képet fehér foltokkal (szimulált micélium).
    """
    def capture_image(self) -> str:
        os.makedirs(CAPTURE_DIRECTORY, exist_ok=True)
        filename = f"mock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(CAPTURE_DIRECTORY, filename)
        
        # Fekete háttér (talaj)
        height, width = 480, 640
        image = np.zeros((height, width, 3), np.uint8)
        
        # Fehér körök rajzolása (micélium telepek)
        # Magic number elkerülése: lokális változók használata
        number_of_patches = 15
        for _ in range(number_of_patches):
            center_x = np.random.randint(0, width)
            center_y = np.random.randint(0, height)
            radius = np.random.randint(20, 80)
            color_white = (255, 255, 255)
            cv2.circle(image, (center_x, center_y), radius, color_white, -1)
            
        cv2.imwrite(filepath, image)
        logger.info(f"[MOCK] Generált kép mentve: {filepath}")
        return filepath