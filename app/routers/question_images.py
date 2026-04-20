import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from .auth import get_current_user
from .. import models  # used for upload auth

router = APIRouter(prefix="/questions", tags=["Question Images"])

MEDIA_ROOT  = Path(os.getenv("MEDIA_ROOT", "media"))
IMAGES_DIR  = MEDIA_ROOT / "question_images"
MAX_IMAGE_MB = 10
ALLOWED     = {"image/jpeg", "image/png", "image/gif", "image/webp"}
EXT_MAP     = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}


def _ensure(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


@router.post("/upload-image", status_code=status.HTTP_201_CREATED)
async def upload_question_image(
    image: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
):
    """Upload an image to attach to a question. Returns the URL to store in image_url."""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    ct = (image.content_type or "").lower()
    if ct not in ALLOWED:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, GIF, or WebP images are accepted")

    raw = await image.read()
    if len(raw) / 1024 / 1024 > MAX_IMAGE_MB:
        raise HTTPException(status_code=413, detail=f"Image must be under {MAX_IMAGE_MB} MB")

    raw_ext = ct.split("/")[-1]
    ext = EXT_MAP.get(raw_ext, "jpg")
    img_id = str(uuid.uuid4())

    _ensure(IMAGES_DIR)
    file_path = IMAGES_DIR / f"{img_id}.{ext}"
    file_path.write_bytes(raw)

    return {"url": f"/api/questions/images/{img_id}.{ext}"}


@router.get("/images/{filename}")
def serve_question_image(filename: str):
    """Serve a stored question image — public, no auth required (images are not sensitive)."""
    if any(c in filename for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = IMAGES_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    ext = filename.rsplit(".", 1)[-1].lower()
    media_types = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }
    return FileResponse(path=str(file_path), media_type=media_types.get(ext, "image/jpeg"))
