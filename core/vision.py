# core/vision.py
from PIL import Image
import numpy as np
import logging
from core.constants import (
    MYCELIUM_LOWER_H, MYCELIUM_LOWER_S, MYCELIUM_LOWER_V,
    MYCELIUM_UPPER_H, MYCELIUM_UPPER_S, MYCELIUM_UPPER_V
)

logger = logging.getLogger(__name__)

class ImageAnalyzer:
    """
    Responsible solely for image analysis (SRP).
    Does not know about the camera or the database.
    """
    
    @staticmethod
    def calculate_mycelium_coverage(image_path: str) -> float:
        """
        Calculates the mycelium (white areas) ratio as a percentage.
        """
        if not image_path:
            return 0.0
            
        try:
            # Convert PIL image to numpy array
            pil_image = Image.open(image_path)
            rgb_image = np.array(pil_image.convert('RGB'))

            # RGB color space (PIL uses RGB not BGR)
            # Normalize to 0-1 range to 0-255
            image_normalized = rgb_image.astype(np.float32) / 255.0
            
            # RGB to HSV conversion (manual, since PIL doesn't support directly)
            # But simpler: detect white color in RGB space
            # White: R, G, B > 150, and equal
            
            # Alternative: convert PIL Image mode to HSV
            # But simple solution: detect white pixels in RGB space
            
            r = rgb_image[:, :, 0].astype(np.float32)
            g = rgb_image[:, :, 1].astype(np.float32)
            b = rgb_image[:, :, 2].astype(np.float32)
            
            # White color: high values on all channels, and similar values
            # General approach: grayscale value > 180 and low saturation
            gray = (r + g + b) / 3.0
            max_val = np.maximum(np.maximum(r, g), b)
            min_val = np.minimum(np.minimum(r, g), b)
            
            # Saturation: (max - min) / max
            saturation = np.where(max_val > 0, (max_val - min_val) / max_val, 0)
            
            # White pixel: high value and low saturation
            white_mask = (gray > MYCELIUM_LOWER_V) & (saturation < 0.2)
            
            # Calculate
            total_pixels = white_mask.size
            white_pixels = np.sum(white_mask)
            
            if total_pixels == 0:
                return 0.0

            coverage_percentage = (white_pixels / total_pixels) * 100.0
            return round(coverage_percentage, 2)

        except Exception as e:
            logger.error(f"Error during image processing: {e}")
            return 0.0