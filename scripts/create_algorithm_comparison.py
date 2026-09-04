"""Create a thesis-ready comparison of the legacy and calibrated masks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.constants import MYCELIUM_ROI_CROP  # noqa: E402
from core.vision import ImageAnalyzer  # noqa: E402


PURPLE = np.array([120.0, 50.0, 210.0], dtype=np.float32)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "arialbd.ttf" if bold else "arial.ttf"
    candidates = [Path("C:/Windows/Fonts") / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def overlay(image: Image.Image, mask: np.ndarray, opacity: float = 0.48) -> Image.Image:
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    pixels[mask] = pixels[mask] * (1.0 - opacity) + PURPLE * opacity
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="RGB")


def roi_box(width: int, height: int) -> tuple[int, int, int, int]:
    left = int(width * MYCELIUM_ROI_CROP["left"] / 100.0)
    top = int(height * MYCELIUM_ROI_CROP["top"] / 100.0)
    right = width - int(width * MYCELIUM_ROI_CROP["right"] / 100.0)
    bottom = height - int(height * MYCELIUM_ROI_CROP["bottom"] / 100.0)
    return left, top, right, bottom


def make_comparison(image_path: Path, output_path: Path) -> tuple[float, float]:
    original = Image.open(image_path).convert("RGB")
    width, height = original.size

    legacy_mask = ImageAnalyzer._create_white_mask(
        original,
        brightness_threshold=150,
        saturation_threshold=0.25,
        expand_edges=True,
    )
    legacy_coverage = float(legacy_mask.mean() * 100.0)
    legacy_panel = overlay(original, legacy_mask)

    left, top, right, bottom = roi_box(width, height)
    roi = original.crop((left, top, right, bottom))
    roi_mask = ImageAnalyzer._create_white_mask(roi, expand_edges=True)
    calibrated_coverage = float(roi_mask.mean() * 100.0)
    calibrated_full_mask = np.zeros((height, width), dtype=bool)
    calibrated_full_mask[top:bottom, left:right] = roi_mask
    calibrated_panel = overlay(original, calibrated_full_mask)

    # Dim the excluded area on the calibrated panel while leaving the ROI intact.
    dim_layer = Image.new("RGBA", original.size, (15, 23, 42, 115))
    clear_roi = Image.new("L", original.size, 255)
    ImageDraw.Draw(clear_roi).rectangle((left, top, right, bottom), fill=0)
    calibrated_panel = Image.composite(
        Image.alpha_composite(calibrated_panel.convert("RGBA"), dim_layer).convert("RGB"),
        calibrated_panel,
        clear_roi,
    )
    ImageDraw.Draw(calibrated_panel).rectangle(
        (left, top, right - 1, bottom - 1), outline=(46, 204, 113), width=max(5, width // 500)
    )

    panel_width = 1180
    panel_height = round(height * panel_width / width)
    legacy_panel = legacy_panel.resize((panel_width, panel_height), Image.Resampling.LANCZOS)
    calibrated_panel = calibrated_panel.resize((panel_width, panel_height), Image.Resampling.LANCZOS)

    margin = 54
    gap = 34
    header = 190
    footer = 125
    canvas = Image.new(
        "RGB",
        (margin * 2 + panel_width * 2 + gap, header + panel_height + footer),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    title_font = font(40, bold=True)
    panel_font = font(29, bold=True)
    body_font = font(23)
    small_font = font(20)

    draw.text((margin, 26), "Micéliumdetektálás összehasonlítása ugyanazon a felvételen", fill="#1f2937", font=title_font)
    draw.text((margin, 82), f"Felvétel: {image_path.name}", fill="#596579", font=body_font)

    old_x = margin
    new_x = margin + panel_width + gap
    label_y = 125
    draw.text((old_x, label_y), f"Régi algoritmus: {legacy_coverage:.2f}%", fill="#512da8", font=panel_font)
    draw.text((new_x, label_y), f"Új módszer: {calibrated_coverage:.2f}%", fill="#512da8", font=panel_font)
    canvas.paste(legacy_panel, (old_x, header))
    canvas.paste(calibrated_panel, (new_x, header))

    footer_y = header + panel_height + 22
    draw.rectangle((margin, footer_y + 2, margin + 26, footer_y + 28), fill=tuple(PURPLE.astype(int)))
    draw.text((margin + 38, footer_y), "Lila: micéliumnak minősített képpontok", fill="#374151", font=body_font)
    draw.text((old_x, footer_y + 43), "Régi: teljes kép, I > 150, S < 0,25", fill="#596579", font=small_font)
    draw.text((new_x, footer_y + 43), "Új: zöld kerettel jelölt ROI, I > 135, S < 0,196", fill="#596579", font=small_font)
    draw.text((new_x, footer_y + 75), "A sötétített külső terület nem része a számításnak.", fill="#596579", font=small_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=94, subsampling=0)
    return legacy_coverage, calibrated_coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    old_value, new_value = make_comparison(args.image, args.output)
    print(f"Legacy: {old_value:.2f}%")
    print(f"Calibrated ROI: {new_value:.2f}%")
    print(f"Saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
