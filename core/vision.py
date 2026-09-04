# core/vision.py
from PIL import Image
import numpy as np
import logging
from core.constants import (
    MYCELIUM_LOWER_H, MYCELIUM_LOWER_S, MYCELIUM_LOWER_V,
    MYCELIUM_UPPER_H, MYCELIUM_UPPER_S, MYCELIUM_UPPER_V,
    MYCELIUM_ROI_CROP,
)

logger = logging.getLogger(__name__)

class ImageAnalyzer:
    """
    Responsible solely for image analysis (SRP).
    Does not know about the camera or the database.
    """
    
    @staticmethod
    def calculate_mycelium_coverage(image_path: str, preprocessing: str = "roi") -> float:
        """
        Calculate visible mycelium coverage as a percentage.

        ``roi`` is the production method: it measures the fixed inner substrate
        region so box walls and reflections are not part of the denominator.
        ``legacy`` preserves the historical full-frame calculation.
        """
        if not image_path:
            return 0.0
            
        try:
            pil_image = Image.open(image_path).convert('RGB').copy()
            if preprocessing == "roi":
                pil_image = ImageAnalyzer._crop_image_edges(
                    pil_image, crop_params=MYCELIUM_ROI_CROP
                )
            elif preprocessing != "legacy":
                raise ValueError(f"Unknown preprocessing mode: {preprocessing}")

            white_pixels, total_pixels = ImageAnalyzer._count_white_pixels(pil_image)
            
            if total_pixels == 0:
                return 0.0

            coverage_percentage = (white_pixels / total_pixels) * 100.0
            return round(coverage_percentage, 2)

        except Exception as e:
            logger.error(f"Error during image processing: {e}")
            return 0.0

    @staticmethod
    def calculate_mycelium_coverage_from_image(
        pil_image: Image.Image,
        preprocessing: str = "legacy",
        crop_params: dict = None,
    ) -> float:
        """Calculate coverage from an in-memory image without touching disk.

        The default remains ``legacy`` because callers such as the comparison
        preview may already pass a cropped image.  Use ``roi`` for a raw camera
        frame; optional ``crop_params`` override the calibrated production ROI.
        """
        try:
            image = pil_image.convert('RGB').copy()
            if preprocessing == "roi":
                image = ImageAnalyzer._crop_image_edges(
                    image, crop_params=crop_params or MYCELIUM_ROI_CROP
                )
            elif preprocessing != "legacy":
                raise ValueError(f"Unknown preprocessing mode: {preprocessing}")

            white_pixels, total_pixels = ImageAnalyzer._count_white_pixels(image)
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
        # Do not apply autocontrast here.  It changes the meaning of the fixed
        # brightness threshold and was observed to undercount late-stage growth.
        # Keeping the preview to a crop-only transform makes it identical to the
        # production ROI measurement and therefore directly comparable.
        return ImageAnalyzer._crop_image_edges(
            img, crop_params=crop_params or MYCELIUM_ROI_CROP
        )

    @staticmethod
    def create_mycelium_mask_image(pil_image: Image.Image) -> Image.Image:
        """Return the exact binary mask used by the coverage calculation."""
        mask = ImageAnalyzer._create_white_mask(pil_image.convert('RGB'))
        return Image.fromarray((mask.astype(np.uint8) * 255), mode='L')

    @staticmethod
    def create_mask_overlay_image(pil_image: Image.Image, opacity: float = 0.45) -> Image.Image:
        """Overlay detected mycelium pixels for visual quality control."""
        image = pil_image.convert('RGB').copy()
        mask = ImageAnalyzer._create_white_mask(image)
        base = np.asarray(image, dtype=np.float32).copy()
        overlay_color = np.array([120.0, 50.0, 210.0], dtype=np.float32)
        alpha = min(1.0, max(0.0, float(opacity)))
        base[mask] = (base[mask] * (1.0 - alpha)) + (overlay_color * alpha)
        return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode='RGB')

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
    def _create_white_mask(
        pil_image: Image.Image,
        brightness_threshold: float = MYCELIUM_LOWER_V,
        saturation_threshold: float = MYCELIUM_UPPER_S / 255.0,
        expand_edges: bool = True,
    ) -> np.ndarray:
        """Classify visible white, low-saturation pixels as mycelium."""
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

        white_mask = (
            (gray > float(brightness_threshold))
            & (saturation < float(saturation_threshold))
        )

        # Expand the mask by one pixel in every direction so fuzzy colony edges count too.
        if expand_edges and white_mask.any():
            padded = np.pad(white_mask, 1, mode='constant', constant_values=False)
            expanded_mask = np.zeros_like(white_mask, dtype=bool)
            height, width = white_mask.shape
            for dy in range(3):
                for dx in range(3):
                    expanded_mask |= padded[dy:dy + height, dx:dx + width]
            white_mask = expanded_mask

        return white_mask

    @staticmethod
    def _count_white_pixels(pil_image: Image.Image) -> tuple:
        white_mask = ImageAnalyzer._create_white_mask(pil_image)

        total_pixels = white_mask.size
        white_pixels = np.sum(white_mask)
        return white_pixels, total_pixels
