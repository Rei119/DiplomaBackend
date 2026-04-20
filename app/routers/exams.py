from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from .. import crud, schemas, models
from ..database import get_db
from .auth import get_current_user

router = APIRouter(prefix="/exams", tags=["Exams"])


@router.get("/by-code/{code}", response_model=schemas.ExamResponse)
def get_exam_by_code(
    code: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Student looks up a published exam by its 5-char code."""
    exam = db.query(models.Exam).filter(
        models.Exam.exam_code == code.upper(),
        models.Exam.status == "published"
    ).first()

    if not exam:
        raise HTTPException(
            status_code=404,
            detail="Код олдсонгүй эсвэл шалгалт нийтлэгдээгүй байна"
        )

    return exam


@router.get("/", response_model=List[schemas.ExamResponse])
def get_exams(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return crud.get_exams(db, user_id=current_user.id, role=current_user.role)


@router.get("/{exam_id}", response_model=schemas.ExamResponse)
def get_exam(
    exam_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    exam = crud.get_exam(db, exam_id=exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if current_user.role == "student" and exam.status != "published":
        raise HTTPException(status_code=403, detail="Exam not available")

    if current_user.role == "teacher" and exam.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return exam


@router.post("/", response_model=schemas.ExamResponse, status_code=status.HTTP_201_CREATED)
def create_exam(
    exam: schemas.ExamCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can create exams")

    return crud.create_exam(db=db, exam=exam, user_id=current_user.id)


@router.put("/{exam_id}", response_model=schemas.ExamResponse)
def update_exam(
    exam_id: str,
    exam: schemas.ExamUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can update exams")

    db_exam = crud.get_exam(db, exam_id=exam_id)
    if not db_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if db_exam.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return crud.update_exam(db=db, exam_id=exam_id, exam=exam)


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exam(
    exam_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can delete exams")

    db_exam = crud.get_exam(db, exam_id=exam_id)
    if not db_exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if db_exam.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    crud.delete_exam(db=db, exam_id=exam_id)
    return None