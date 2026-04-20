

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CameraClip, Submission
from .auth import get_current_user

router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────
# Override via environment variable in production.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "media"))
CLIPS_DIR = MEDIA_ROOT / "camera_clips"
MAX_CLIP_SIZE_MB = int(os.getenv("MAX_CLIP_SIZE_MB", "10"))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ── POST /api/submissions/clips ───────────────────────────────────────────────
@router.post("/clips", status_code=status.HTTP_201_CREATED)
async def upload_clip(
    submission_id: str = Form(...),
    timestamp: int = Form(...),          # epoch ms from client
    clip: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Called by the student's browser immediately after a look-down event.
    Accepts a short WebM blob and stores it on disk.
    """
    # ── Validate submission exists and belongs to the caller ──────────────────
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Students may only upload for their own submission;
    # teachers / admins may upload on behalf of anyone (e.g. re-processing).
    if current_user.role == "student" and submission.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # ── Validate file ─────────────────────────────────────────────────────────
    content_type = clip.content_type or ""
    if not content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Only video files are accepted")

    raw = await clip.read()
    size_mb = len(raw) / (1024 * 1024)
    if size_mb > MAX_CLIP_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Clip exceeds {MAX_CLIP_SIZE_MB} MB limit ({size_mb:.1f} MB received)",
        )

    # ── Persist to disk ───────────────────────────────────────────────────────
    clip_id = str(uuid.uuid4())
    sub_clip_dir = CLIPS_DIR / submission_id
    _ensure_dir(sub_clip_dir)
    file_path = sub_clip_dir / f"{clip_id}.webm"
    file_path.write_bytes(raw)

    # ── Insert DB record ──────────────────────────────────────────────────────
    db_clip = CameraClip(
        id=clip_id,
        submission_id=submission_id,
        event_timestamp=timestamp,
        file_path=str(file_path.relative_to(MEDIA_ROOT)),
        file_size=len(raw),
    )
    db.add(db_clip)
    db.commit()
    db.refresh(db_clip)

    return {"id": clip_id, "submission_id": submission_id, "timestamp": timestamp}


# ── GET /api/submissions/{submission_id}/clips ────────────────────────────────
@router.get("/{submission_id}/clips")
def list_clips(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns the list of camera clips for a submission.
    Only teachers and admins may call this endpoint.
    """
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    clips = (
        db.query(CameraClip)
        .filter(CameraClip.submission_id == submission_id)
        .order_by(CameraClip.event_timestamp)
        .all()
    )

    return {
        "submission_id": submission_id,
        "clips": [
            {
                "id": c.id,
                "submission_id": c.submission_id,
                "timestamp": c.event_timestamp,
                # URL that the teacher's browser will GET to stream the video
                "url": f"/api/submissions/clips/{c.id}/stream",
                "file_size": c.file_size,
                "created_at": c.created_at.isoformat(),
            }
            for c in clips
        ],
    }


# ── GET /api/submissions/clips/{clip_id}/stream ───────────────────────────────
@router.get("/clips/{clip_id}/stream")
def stream_clip(
    clip_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Serve the raw WebM file to the teacher's browser."""
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    clip = db.query(CameraClip).filter(CameraClip.id == clip_id).first()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    full_path = MEDIA_ROOT / clip.file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Clip file missing from disk")

    return FileResponse(
        path=str(full_path),
        media_type="video/webm",
        filename=f"lookdown_{clip.event_timestamp}.webm",
    )