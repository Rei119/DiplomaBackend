from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import uuid
import time

from .. import models
from ..database import get_db
from .auth import get_current_user

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── Student: start a session ──────────────────────────────────────────────────

@router.post("/start")
def start_session(
    body: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Students only")

    exam_id: str = body.get("exam_id", "")
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    now = _now_ms()

    # Upsert: if a session already exists for this student+exam, reuse it
    existing = (
        db.query(models.ExamSession)
        .filter(
            models.ExamSession.exam_id == exam_id,
            models.ExamSession.student_id == current_user.id,
            models.ExamSession.status == "active",
        )
        .first()
    )
    if existing:
        existing.last_heartbeat = now
        db.commit()
        return {"session_id": existing.id}

    session = models.ExamSession(
        id=str(uuid.uuid4()),
        exam_id=exam_id,
        student_id=current_user.id,
        student_id_number=body.get("student_id_number"),
        student_major=body.get("student_major"),
        started_at=now,
        last_heartbeat=now,
        tab_switches=0,
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id}


# ── Student: heartbeat ────────────────────────────────────────────────────────

@router.patch("/{session_id}/heartbeat")
def heartbeat(
    session_id: str,
    body: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(models.ExamSession).filter(
        models.ExamSession.id == session_id,
        models.ExamSession.student_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.last_heartbeat = _now_ms()
    session.tab_switches = body.get("tab_switches", session.tab_switches)
    db.commit()
    return {"ok": True}


# ── Student: mark submitted ───────────────────────────────────────────────────

@router.patch("/{session_id}/submit")
def mark_submitted(
    session_id: str,
    body: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(models.ExamSession).filter(
        models.ExamSession.id == session_id,
        models.ExamSession.student_id == current_user.id,
    ).first()
    if not session:
        return {"ok": True}  # graceful — don't block submission

    session.status = "submitted"
    session.last_heartbeat = _now_ms()
    session.submission_id = body.get("submission_id")
    db.commit()
    return {"ok": True}


# ── Teacher: get live sessions for an exam (by code or id) ───────────────────

@router.get("/exam/{exam_id}")
def get_live_sessions(
    exam_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your exam")

    now = _now_ms()
    cutoff = now - 3 * 60 * 1000  # 3 min without heartbeat → abandoned

    sessions = (
        db.query(models.ExamSession)
        .options(joinedload(models.ExamSession.student))
        .filter(models.ExamSession.exam_id == exam_id)
        .order_by(models.ExamSession.started_at.desc())
        .all()
    )

    result = []
    for s in sessions:
        # Auto-mark abandoned if no heartbeat and still "active"
        if s.status == "active" and s.last_heartbeat < cutoff:
            s.status = "abandoned"
            db.commit()

        # Fetch linked submission score
        score = None
        if s.submission_id:
            sub = db.query(models.Submission).filter(
                models.Submission.id == s.submission_id
            ).first()
            if sub:
                score = sub.total_score

        elapsed_ms = (s.last_heartbeat or s.started_at) - s.started_at

        result.append({
            "session_id": s.id,
            "student_id": s.student_id,
            "username": s.student.username if s.student else None,
            "full_name": s.student.full_name if s.student else None,
            "student_id_number": s.student_id_number,
            "student_major": s.student_major,
            "started_at": s.started_at,
            "last_heartbeat": s.last_heartbeat,
            "elapsed_ms": elapsed_ms,
            "tab_switches": s.tab_switches,
            "status": s.status,
            "score": score,
        })

    return {
        "exam_id": exam_id,
        "exam_title": exam.title,
        "exam_code": exam.exam_code,
        "sessions": result,
    }


@router.get("/by-code/{code}")
def get_live_sessions_by_code(
    code: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")

    exam = db.query(models.Exam).filter(
        models.Exam.exam_code == code.upper()
    ).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam code not found")
    if exam.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your exam")

    return get_live_sessions(exam.id, current_user, db)
