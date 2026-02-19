# drivers/camera.py
import abc
import numpy as np
import os
import logging
import subprocess
from datetime import datetime
from PIL import Image
from core.constants import CAPTURE_DIRECTORY

logger = logging.getLogger(__name__)

class CameraDriver(abc.ABC):
    """
    Abstract interface (follows DIP).
    High-level modules (Controller) depend on this, not on RealCameraDriver.
    """
    @abc.abstractmethod
    def capture_image(self) -> str:
        """Takes a photo and returns the file path."""
        pass

class RealCameraDriver(CameraDriver):
    """
    Raspberry Pi Camera v3 (IMX708) implementation using rpicam.
    """
    def __init__(self):
        # Check if rpicam-still is available
        try:
            result = subprocess.run(['which', 'rpicam-still'], 
                                  capture_output=True, timeout=5)
            self.rpicam_available = result.returncode == 0
            
            if self.rpicam_available:
                logger.info("rpicam-still connected.")
            else:
                logger.warning("rpicam-still not available. Falling back to MockCameraDriver.")
                self.mock = MockCameraDriver()
        except Exception as e:
            logger.warning(f"rpicam check failed: {e}")
            self.rpicam_available = False
            self.mock = MockCameraDriver()
    
    def capture_image(self) -> str:
        # If rpicam is not available, use Mock
        if not self.rpicam_available:
            return self.mock.capture_image()
            
        # Ensure the directory exists
        os.makedirs(CAPTURE_DIRECTORY, exist_ok=True)
        
        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(CAPTURE_DIRECTORY, filename)
        
        try:
            # rpicam-still command: takes a photo at 1920x1080 resolution
            cmd = [
                'rpicam-still',
                '-o', filepath,
                '--width', '1920',
                '--height', '1080',
                '-t', '1000'  # timeout: 1000ms
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            
            if result.returncode == 0 and os.path.exists(filepath):
                logger.info(f"Image successfully saved: {filepath}")
                return filepath
            else:
                logger.error(f"rpicam error: {result.stderr.decode()}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("rpicam timeout")
            return None
        except Exception as e:
            logger.error(f"Camera error: {e}")
            return None

class MockCameraDriver(CameraDriver):
    """
    For testing (Mock).
    Generates a black image with white spots (simulated mycelium).
    """
    def capture_image(self) -> str:
        os.makedirs(CAPTURE_DIRECTORY, exist_ok=True)
        filename = f"mock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(CAPTURE_DIRECTORY, filename)
        
        # Black background (soil)
        height, width = 480, 640
        image = np.zeros((height, width, 3), np.uint8)
        
        # White circles for mycelium patches
        # Avoid magic numbers: use local variables
        number_of_patches = 15
        for _ in range(number_of_patches):
            center_x = np.random.randint(0, width)
            center_y = np.random.randint(0, height)
            radius = np.random.randint(20, 80)
            
            # Draw white circle on numpy array
            y, x = np.ogrid[:height, :width]
            mask = (x - center_x)**2 + (y - center_y)**2 <= radius**2
            image[mask] = [255, 255, 255]
            
        # Convert numpy array to PIL Image and save
        pil_image = Image.fromarray(image.astype('uint8'), 'RGB')
        pil_image.save(filepath)
        logger.info(f"[MOCK] Generated image saved: {filepath}")
        return filepath