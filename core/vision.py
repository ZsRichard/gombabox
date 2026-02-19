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
    Kizárólag a képelemzésért felelős osztály (SRP).
    Nem tud semmit a kameráról vagy az adatbázisról.
    """
    
    @staticmethod
    def calculate_mycelium_coverage(image_path: str) -> float:
        """
        Kiszámolja a micélium (fehér területek) arányát százalékban.
        """
        if not image_path:
            return 0.0
            
        try:
            # PIL-ből numpy array-re
            pil_image = Image.open(image_path)
            rgb_image = np.array(pil_image.convert('RGB'))

            # BGR-ből HSV konverzió (PIL RGB-ből kell)
            # Normalizálunk 0-1 tartományra, majd HSV-re
            image_normalized = rgb_image.astype(np.float32) / 255.0
            
            # RGB to HSV konverzió (manual, mivel PIL nem támogatja közvetlenül)
            # De egyszerűb: fehér szín detektálása a RGB térben
            # Fehér: R, G, B > 150, és egyformák
            
            # Alternatíva: PIL Image módot HSV-re konvertálni
            # De egyszerü megoldás: fehér pixel detektálása RGB-ben
            
            r = rgb_image[:, :, 0].astype(np.float32)
            g = rgb_image[:, :, 1].astype(np.float32)
            b = rgb_image[:, :, 2].astype(np.float32)
            
            # Fehér szín: magas értékek minden csatornán, és hasonló értékek
            # Általános megközelítés: grayscale értéke > 180 és alacsony szaturáció
            gray = (r + g + b) / 3.0
            max_val = np.maximum(np.maximum(r, g), b)
            min_val = np.minimum(np.minimum(r, g), b)
            
            # Szaturáció: (max - min) / max
            saturation = np.where(max_val > 0, (max_val - min_val) / max_val, 0)
            
            # Fehér pixel: magas érték és alacsony szaturáció
            white_mask = (gray > MYCELIUM_LOWER_V) & (saturation < 0.2)
            
            # Számítás
            total_pixels = white_mask.size
            white_pixels = np.sum(white_mask)
            
            if total_pixels == 0:
                return 0.0

            coverage_percentage = (white_pixels / total_pixels) * 100.0
            return round(coverage_percentage, 2)

        except Exception as e:
            logger.error(f"Hiba a képfeldolgozás során: {e}")
            return 0.0