from sqlalchemy.orm import Session
from passlib.context import CryptContext
from fastapi import HTTPException
import uuid
import secrets
import string
from sqlalchemy.orm import Session, joinedload
from . import models, schemas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============= Authentication =============

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# ============= User CRUD =============

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def get_user_by_id(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_user_by_google_id(db: Session, google_id: str):
    return db.query(models.User).filter(models.User.google_id == google_id).first()

def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(
        id=str(uuid.uuid4()),
        username=user.username,
        email=user.email,
        password=hashed_password,
        role=user.role,
        full_name=user.full_name,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def create_google_user(db: Session, username: str, email: str, role: str, google_id: str):
    """Create a new user from Google OAuth — no password needed."""
    random_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    db_user = models.User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        password=get_password_hash(random_password),
        role=role,
        google_id=google_id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def link_google_account(db: Session, user: models.User, google_id: str):
    """Link an existing account to a Google ID."""
    user.google_id = google_id
    db.commit()
    db.refresh(user)
    return user

def update_user(db: Session, user: models.User, update_data: schemas.UserUpdate):
    """Update username and/or password. Verifies current_password if changing password."""
    if update_data.username:
        user.username = update_data.username

    if update_data.password:
        if update_data.current_password:
            if not verify_password(update_data.current_password, user.password):
                raise HTTPException(status_code=400, detail="Одоогийн нууц үг буруу байна")
        user.password = get_password_hash(update_data.password)

    db.commit()
    db.refresh(user)
    return user

# ============= Exam CRUD =============

def get_exams(db: Session, user_id: str, role: str):
    if role == "student":
        return db.query(models.Exam).filter(models.Exam.status == "published").all()
    elif role == "teacher":
        return db.query(models.Exam).filter(models.Exam.creator_id == user_id).all()
    return db.query(models.Exam).all()

def get_exam(db: Session, exam_id: str):
    return db.query(models.Exam).filter(models.Exam.id == exam_id).first()

def create_exam(db: Session, exam: schemas.ExamCreate, user_id: str):
    db_exam = models.Exam(
        id=str(uuid.uuid4()),
        **exam.model_dump(),
        creator_id=user_id
    )
    db.add(db_exam)
    db.commit()
    db.refresh(db_exam)
    return db_exam

def update_exam(db: Session, exam_id: str, exam: schemas.ExamUpdate):
    db_exam = get_exam(db, exam_id)
    if db_exam:
        for key, value in exam.model_dump(exclude_unset=True).items():
            setattr(db_exam, key, value)
        db.commit()
        db.refresh(db_exam)
    return db_exam

def delete_exam(db: Session, exam_id: str):
    db_exam = get_exam(db, exam_id)
    if db_exam:
        db.delete(db_exam)
        db.commit()
    return True

# ============= Submission CRUD =============


def get_submissions(db: Session, user_id: str, role: str):
    query = db.query(models.Submission).options(
        joinedload(models.Submission.student)
    )
    if role == "student":
        query = query.filter(models.Submission.student_id == user_id)
    elif role == "teacher":
        query = query.join(models.Exam).filter(
            models.Exam.creator_id == user_id
        )
    submissions = query.all()
    # Attach username dynamically
    for sub in submissions:
        sub.student_username = sub.student.username if sub.student else None
    return submissions

def create_submission(db: Session, submission: schemas.SubmissionCreate, exam_id: str, user_id: str, status: str, individual_scores: dict = None, total_score: float = None):
    # Exclude fields that don't exist on the model
    data = submission.model_dump(exclude={'camera_events'})
    db_submission = models.Submission(
        id=str(uuid.uuid4()),
        student_id=user_id,
        exam_id=exam_id,
        status=status,
        total_score=total_score,
        ai_grading_results=individual_scores,
        **data
    )
    db.add(db_submission)
    db.commit()
    db.refresh(db_submission)
    return db_submission

def update_submission_score(db: Session, submission_id: str, score: float, ai_results: dict = None):
    db_submission = db.query(models.Submission).filter(models.Submission.id == submission_id).first()
    if db_submission:
        db_submission.total_score = score
        if ai_results:
            db_submission.ai_grading_results = ai_results
        db.commit()
        db.refresh(db_submission)
    return db_submission