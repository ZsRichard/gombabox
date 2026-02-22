# drivers/camera.py
import abc
import numpy as np
import os
import logging
import subprocess
from datetime import datetime
from PIL import Image
from core.constants import get_capture_directory

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
        
        # Get the appropriate capture directory (SSD or SD card fallback)
        capture_dir = get_capture_directory()
        
        # Ensure the directory exists
        os.makedirs(capture_dir, exist_ok=True)
        
        filename = f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(capture_dir, filename)
        
        try:
            # rpicam-still command: optimized for high-quality macro focus at 25-30cm distance
            # Camera Module v3 wide native resolution: 4608x2592 (11.9MP)
            # (4056x3040 causes unwanted cropping/rescaling from native format)
            # Focus parameters:
            #   --autofocus-mode continuous: continuous auto-focus for sharp macro shots
            #   --autofocus-range macro: optimized focus range for 25-30cm macro photography
            #   --autofocus-on-capture: triggers AF scan just before capturing
            #   --autofocus-speed fast: faster focus acquisition
            # -t 5000: timeout of 5000ms for robust focus before capture
            # -q 95: high JPEG quality for best image detail
            # --sharpness 1.5: enhanced edge sharpness to combat macro blur
            # --contrast 1.2: increased contrast for mycelium visibility
            # --denoise cdn_fast: fast denoising to reduce edge artifacts
            cmd = [
                'rpicam-still',
                '-o', filepath,
                '--width', '4608',                    # Native sensor resolution - full width, no crop
                '--height', '2592',                   # Native sensor resolution
                '--autofocus-mode', 'continuous',     # Continuous auto-focus for macro
                '--autofocus-range', 'macro',         # Optimize for 25-30cm macro distance
                '--autofocus-on-capture',             # Trigger AF scan at capture time
                '--autofocus-speed', 'fast',          # Faster focus acquisition
                '-t', '5000',                         # Timeout: 5000ms for macro focus (must update CAMERA_FOCUS_TIME_MS if changed)
                '-q', '95',                           # High JPEG quality
                '--sharpness', '1.5',                 # Enhanced edge sharpness for macro blur combat
                '--contrast', '1.2',                  # Increased contrast for mycelium visibility
                '--denoise', 'cdn_fast'               # Fast denoising to improve edge clarity
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
        # Get the appropriate capture directory (SSD or SD card fallback)
        capture_dir = get_capture_directory()
        
        os.makedirs(capture_dir, exist_ok=True)
        filename = f"mock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(capture_dir, filename)
        
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