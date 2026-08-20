from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


class MemeGenerationError(ValueError):
    pass


class MemeGenerator:
    max_pixels = 40_000_000
    max_side = 2500

    def __init__(self) -> None:
        self.font_path = Path(__file__).parents[1] / "cogs" / "fonts" / "Impact.ttf"

    def generate(self, image_bytes: bytes, top_text: str, bottom_text: str) -> bytes:
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
        except (UnidentifiedImageError, OSError) as error:
            raise MemeGenerationError("El archivo no es una imagen válida.") from error

        if image.width * image.height > self.max_pixels:
            raise MemeGenerationError("La imagen tiene demasiados píxeles.")

        image = self._resize(image)
        draw = ImageDraw.Draw(image)
        margin = max(12, round(min(image.size) * 0.035))
        font, top_lines, bottom_lines, line_height = self._get_layout(
            image.size,
            top_text,
            bottom_text,
            margin,
        )
        stroke_width = max(2, font.size // 16)
        self._draw_block(draw, image.width, margin, top_lines, font, line_height, stroke_width)

        bottom_height = len(bottom_lines) * line_height
        bottom_y = image.height - margin - bottom_height
        self._draw_block(draw, image.width, bottom_y, bottom_lines, font, line_height, stroke_width)

        output = BytesIO()
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        background.save(output, format="JPEG", quality=92, optimize=True)
        output.seek(0)
        return output.getvalue()

    def _resize(self, image: Image.Image) -> Image.Image:
        largest_side = max(image.size)
        if largest_side <= self.max_side:
            return image

        scale = self.max_side / largest_side
        size = (round(image.width * scale), round(image.height * scale))
        return image.resize(size, Image.Resampling.LANCZOS)

    def _get_layout(
        self,
        image_size: tuple[int, int],
        top_text: str,
        bottom_text: str,
        margin: int,
    ) -> tuple[ImageFont.FreeTypeFont, list[str], list[str], int]:
        width, height = image_size
        max_width = width - margin * 2
        start_size = max(18, round(min(width * 0.13, height * 0.22)))

        for font_size in range(start_size, 11, -2):
            font = ImageFont.truetype(self.font_path, font_size)
            stroke_width = max(2, font_size // 16)
            top_lines = self._wrap_text(top_text, font, max_width, stroke_width)
            bottom_lines = self._wrap_text(bottom_text, font, max_width, stroke_width)
            line_height = self._line_height(font, stroke_width)

            if (len(top_lines) + len(bottom_lines)) * line_height <= height - margin * 2:
                return font, top_lines, bottom_lines, line_height

        raise MemeGenerationError("El texto es demasiado largo para esta imagen.")

    def _wrap_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        stroke_width: int,
    ) -> list[str]:
        if not text.strip():
            return []

        lines: list[str] = []
        for paragraph in text.upper().splitlines() or [text.upper()]:
            words = paragraph.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if self._text_width(candidate, font, stroke_width) <= max_width:
                    current = candidate
                    continue

                if current:
                    lines.append(current)
                    current = ""

                while self._text_width(word, font, stroke_width) > max_width:
                    part, word = self._split_word(word, font, max_width, stroke_width)
                    lines.append(part)
                current = word

            if current:
                lines.append(current)

        return lines

    def _split_word(
        self,
        word: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        stroke_width: int,
    ) -> tuple[str, str]:
        for index in range(len(word) - 1, 0, -1):
            if self._text_width(word[:index], font, stroke_width) <= max_width:
                return word[:index], word[index:]
        return word[:1], word[1:]

    def _text_width(self, text: str, font: ImageFont.FreeTypeFont, stroke_width: int) -> int:
        left, _, right, _ = font.getbbox(text, stroke_width=stroke_width)
        return right - left

    def _line_height(self, font: ImageFont.FreeTypeFont, stroke_width: int) -> int:
        _, top, _, bottom = font.getbbox("ÁY", stroke_width=stroke_width)
        return bottom - top + max(2, font.size // 12)

    def _draw_block(
        self,
        draw: ImageDraw.ImageDraw,
        width: int,
        y: int,
        lines: list[str],
        font: ImageFont.FreeTypeFont,
        line_height: int,
        stroke_width: int,
    ) -> None:
        for line in lines:
            left, _, right, _ = font.getbbox(line, stroke_width=stroke_width)
            x = (width - (right - left)) / 2 - left
            draw.text(
                (x, y),
                line,
                font=font,
                fill="white",
                stroke_width=stroke_width,
                stroke_fill="black",
            )
            y += line_height
