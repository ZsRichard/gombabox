# core/vision.py
from PIL import Image, ImageFilter, ImageOps
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
    def calculate_mycelium_coverage(image_path: str, preprocessing: str = "legacy") -> float:
        """
        Calculates the mycelium (white areas) ratio as a percentage.
        """
        if not image_path:
            return 0.0
            
        try:
            pil_image = Image.open(image_path).convert('RGB').copy()
            white_pixels, total_pixels = ImageAnalyzer._count_white_pixels(pil_image)
            
            if total_pixels == 0:
                return 0.0

            coverage_percentage = (white_pixels / total_pixels) * 100.0
            return round(coverage_percentage, 2)

        except Exception as e:
            logger.error(f"Error during image processing: {e}")
            return 0.0

    @staticmethod
    def calculate_mycelium_coverage_from_image(pil_image: Image.Image) -> float:
        """Calculate coverage from an in-memory PIL image without touching disk."""
        try:
            white_pixels, total_pixels = ImageAnalyzer._count_white_pixels(pil_image.convert('RGB').copy())
            if total_pixels == 0:
                return 0.0

            coverage_percentage = (white_pixels / total_pixels) * 100.0
            return round(coverage_percentage, 2)
        except Exception as e:
            logger.error(f"Error during image processing: {e}")
            return 0.0

    @staticmethod
    def create_preprocessing_preview_image(pil_image: Image.Image, crop_params: dict = None) -> Image.Image:
        """Create a non-destructive preview version of the image in memory.

        crop_params (optional): dict with keys 'top','left','right','bottom' expressed as
        percentages (0-100). When provided, these override the automatic extra trims.
        """
        img = pil_image.convert('RGB').copy()
        preview_image = ImageAnalyzer._crop_image_edges(img, crop_params=crop_params)
        preview_image = ImageOps.autocontrast(preview_image)
        preview_image = preview_image.filter(ImageFilter.GaussianBlur(radius=1.0))
        return preview_image

    @staticmethod
    def _crop_image_edges(pil_image: Image.Image, crop_params: dict = None) -> Image.Image:
        """Automatically crop dark borders (box walls) by detecting inner bright region.

        Strategy:
        - Convert to grayscale and compute mean intensity per row/column.
        - Find the first/last row/column where mean intensity rises above a threshold.
        - Apply a small padding and return the cropped image.
        Falls back to a conservative fixed-percent crop if detection fails.
        """
        width, height = pil_image.size
        if width < 20 or height < 20:
            return pil_image

        if crop_params:
            def pct_to_px(pct, dim):
                try:
                    return max(0, int((float(pct) / 100.0) * dim))
                except Exception:
                    return 0

            left = pct_to_px(crop_params.get('left', 0), width)
            top = pct_to_px(crop_params.get('top', 0), height)
            right = width - pct_to_px(crop_params.get('right', 0), width)
            bottom = height - pct_to_px(crop_params.get('bottom', 0), height)

            if right <= left + 1 or bottom <= top + 1:
                return pil_image

            return pil_image.crop((left, top, right, bottom))

        try:
            gray = np.array(pil_image.convert('L'), dtype=np.float32) / 255.0

            row_mean = gray.mean(axis=1)
            col_mean = gray.mean(axis=0)

            # Compute adaptive thresholds based on medians; ensures resilience to lighting
            row_med = float(np.median(row_mean))
            col_med = float(np.median(col_mean))

            # Use a multiplier < 1.0 so threshold stays below the median in bright images
            row_thr = max(0.08, row_med * 0.6)
            col_thr = max(0.08, col_med * 0.6)

            # find top
            top_idx = 0
            for i, v in enumerate(row_mean):
                if v >= row_thr:
                    top_idx = i
                    break

            bottom_idx = height - 1
            for i, v in enumerate(row_mean[::-1]):
                if v >= row_thr:
                    bottom_idx = height - 1 - i
                    break

            left_idx = 0
            for i, v in enumerate(col_mean):
                if v >= col_thr:
                    left_idx = i
                    break

            right_idx = width - 1
            for i, v in enumerate(col_mean[::-1]):
                if v >= col_thr:
                    right_idx = width - 1 - i
                    break

            # Apply small padding (2% of dimension) to avoid cutting near edges
            pad_x = max(1, int(width * 0.02))
            pad_y = max(1, int(height * 0.02))

            left = max(0, left_idx - pad_x)
            top = max(0, top_idx - pad_y)
            right = min(width, right_idx + pad_x)
            bottom = min(height, bottom_idx + pad_y)

            # Apply asymmetric extra trimming only in automatic mode.
            extra_left = max(0, int(width * 0.05))
            extra_top = max(0, int(height * 0.06))
            extra_right = max(0, int(width * 0.03))

            left = min(left + extra_left, right - 2)
            top = min(top + extra_top, bottom - 2)
            right = max(right - extra_right, left + 2)

            # Validate size
            if right - left < max(10, int(width * 0.3)) or bottom - top < max(10, int(height * 0.3)):
                # detection failed or too small — fallback to fixed 8% crop
                crop_x = max(1, int(width * 0.08))
                crop_y = max(1, int(height * 0.08))
                left = crop_x
                top = crop_y
                right = width - crop_x
                bottom = height - crop_y

            if right <= left + 1 or bottom <= top + 1:
                return pil_image

            return pil_image.crop((left, top, right, bottom))
        except Exception:
            # On any error, do conservative fixed-percent crop
            crop_x = max(1, int(width * 0.08))
            crop_y = max(1, int(height * 0.08))
            left = crop_x
            top = crop_y
            right = width - crop_x
            bottom = height - crop_y
            if right <= left + 1 or bottom <= top + 1:
                return pil_image
            return pil_image.crop((left, top, right, bottom))

    @staticmethod
    def _count_white_pixels(pil_image: Image.Image) -> tuple:
        rgb_image = np.array(pil_image)

        r = rgb_image[:, :, 0].astype(np.float32)
        g = rgb_image[:, :, 1].astype(np.float32)
        b = rgb_image[:, :, 2].astype(np.float32)

        gray = (r + g + b) / 3.0
        max_val = np.maximum(np.maximum(r, g), b)
        min_val = np.minimum(np.minimum(r, g), b)

        with np.errstate(divide='ignore', invalid='ignore'):
            saturation = np.divide(
                max_val - min_val,
                max_val,
                out=np.zeros_like(max_val),
                where=max_val > 0
            )

        white_mask = (gray > MYCELIUM_LOWER_V) & (saturation < 0.2)
        total_pixels = white_mask.size
        white_pixels = np.sum(white_mask)
        return white_pixels, total_pixels