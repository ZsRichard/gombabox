import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from core.vision import ImageAnalyzer
from scripts.calibrate_coverage_thresholds import evaluate


class ImageAnalyzerCoverageTests(unittest.TestCase):
    def test_roi_mode_excludes_bright_box_walls(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[:, :] = (25, 25, 25)
        image[:20, :] = (255, 255, 255)
        image[20:91, 20:86] = (100, 80, 45)
        image[40:60, 40:60] = (230, 230, 230)

        pil_image = Image.fromarray(image, "RGB")
        legacy = ImageAnalyzer.calculate_mycelium_coverage_from_image(pil_image)
        roi = ImageAnalyzer.calculate_mycelium_coverage_from_image(
            pil_image, preprocessing="roi"
        )

        self.assertGreater(legacy, roi)
        # The 20x20 patch becomes 22x22 because the production mask expands
        # fuzzy edges by one pixel in each direction.
        self.assertAlmostEqual(roi, 9.74, delta=0.25)

    def test_file_api_defaults_to_roi_and_keeps_legacy_mode(self):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[:, :] = (20, 20, 20)
        image[:20, :] = (255, 255, 255)
        image[20:91, 20:86] = (100, 80, 45)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.png"
            Image.fromarray(image, "RGB").save(path)

            roi = ImageAnalyzer.calculate_mycelium_coverage(str(path))
            legacy = ImageAnalyzer.calculate_mycelium_coverage(
                str(path), preprocessing="legacy"
            )

        self.assertEqual(roi, 0.0)
        self.assertGreater(legacy, 0.0)

    def test_preview_is_crop_only(self):
        gradient = np.linspace(80, 180, 100, dtype=np.uint8)
        image = np.repeat(gradient[np.newaxis, :, np.newaxis], 100, axis=0)
        image = np.repeat(image, 3, axis=2)
        pil_image = Image.fromarray(image, "RGB")
        crop = {"top": 10, "left": 10, "right": 10, "bottom": 10}

        expected = ImageAnalyzer._crop_image_edges(pil_image, crop)
        actual = ImageAnalyzer.create_preprocessing_preview_image(pil_image, crop)

        self.assertTrue(np.array_equal(np.asarray(expected), np.asarray(actual)))

    def test_mask_pixel_count_matches_reported_coverage(self):
        image = np.full((40, 50, 3), (80, 60, 30), dtype=np.uint8)
        image[10:30, 15:35] = (220, 220, 220)
        pil_image = Image.fromarray(image, "RGB")

        mask = np.asarray(ImageAnalyzer.create_mycelium_mask_image(pil_image)) > 0
        coverage = ImageAnalyzer.calculate_mycelium_coverage_from_image(pil_image)

        self.assertAlmostEqual(coverage, mask.mean() * 100.0, places=2)

    def test_threshold_calibration_metrics_for_exact_mask(self):
        image = np.full((40, 50, 3), (80, 60, 30), dtype=np.uint8)
        image[10:30, 15:35] = (220, 220, 220)
        pil_image = Image.fromarray(image, "RGB")
        reference = ImageAnalyzer._create_white_mask(pil_image)

        metrics = evaluate([("synthetic", pil_image, reference)], 150, 0.25)

        self.assertEqual(metrics["coverage_mae_pp"], 0.0)
        self.assertEqual(metrics["mean_iou"], 1.0)
        self.assertEqual(metrics["mean_dice"], 1.0)


if __name__ == "__main__":
    unittest.main()
