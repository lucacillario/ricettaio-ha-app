from __future__ import annotations

import io
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImageError(ValueError):
    pass


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ImageStore:
    def __init__(self, uploads_dir: Path) -> None:
        self.uploads_dir = uploads_dir

    async def save_cover(self, recipe_id: str, upload: UploadFile) -> tuple[Path, Path]:
        if upload.content_type not in ALLOWED_CONTENT_TYPES:
            raise InvalidImageError("Sono accettate solo immagini JPEG, PNG o WebP")
        content = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(content) > MAX_IMAGE_BYTES:
            raise InvalidImageError("L'immagine supera il limite di 10 MB")
        try:
            image = Image.open(io.BytesIO(content))
            image.verify()
            image = Image.open(io.BytesIO(content))
            image = ImageOps.exif_transpose(image).convert("RGB")
        except (UnidentifiedImageError, OSError) as error:
            raise InvalidImageError("Il file non è un'immagine valida") from error

        recipe_dir = self.uploads_dir / "covers" / recipe_id
        recipe_dir.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        full_path = recipe_dir / f"{token}.webp"
        thumbnail_path = recipe_dir / f"{token}-thumb.webp"

        full = image.copy()
        full.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        full.save(full_path, "WEBP", quality=88, method=6)

        thumbnail = image.copy()
        thumbnail.thumbnail((720, 480), Image.Resampling.LANCZOS)
        thumbnail.save(thumbnail_path, "WEBP", quality=82, method=6)
        return full_path, thumbnail_path

    @staticmethod
    def delete_files(*paths: Path | None) -> None:
        for path in paths:
            if path is None:
                continue
            with suppress(OSError):
                path.unlink(missing_ok=True)
