from sqlalchemy import Column, String, Integer, Boolean, BigInteger, Float, ForeignKey, DateTime, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # teacher, student, admin
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    google_id = Column(String, unique=True, index=True, nullable=True)

    created_exams = relationship("Exam", back_populates="creator", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="student", cascade="all, delete-orphan")


class Exam(Base):
    __tablename__ = "exams"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    questions = Column(JSON, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    passing_score = Column(Integer, nullable=False)
    max_tab_switches = Column(Integer, default=3)
    auto_fail_on_cheat = Column(Boolean, default=True)
    tab_switch_deduct_points = Column(Integer, default=0)
    shuffle_questions = Column(Boolean, default=False)
    show_results_immediately = Column(Boolean, default=False)
    status = Column(String, default="draft")  # draft, published, archived
    exam_code = Column(String, unique=True, index=True, nullable=True)

    creator_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"))
    creator = relationship("User", back_populates="created_exams")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submissions = relationship("Submission", back_populates="exam", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, index=True)

    student_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"))
    student = relationship("User", back_populates="submissions")

    exam_id = Column(String, ForeignKey("exams.id", ondelete="CASCADE"))
    exam = relationship("Exam", back_populates="submissions")

    answers = Column(JSON, nullable=False)
    tab_switches = Column(Integer, default=0)

    # ── Camera / gaze tracking ─────────────────────────────────────────────
    # Only "looking down" is tracked now (head tilt + eye gaze combined).
    look_down_count = Column(Integer, default=0)
    # Legacy columns kept so existing rows don't break; no longer written to.
    look_down_duration = Column(Float, default=0.0)
    behavior_score = Column(Integer, default=100)
    # ──────────────────────────────────────────────────────────────────────

    start_time = Column(BigInteger, nullable=False)
    submit_time = Column(BigInteger, nullable=False)

    # Student metadata
    student_id_number = Column(String, nullable=True)
    student_major = Column(String, nullable=True)

    status = Column(String, nullable=False)  # completed, failed, grading
    total_score = Column(Float, nullable=True)

    ai_grading_results = Column(JSON, nullable=True)
    plagiarism_results = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to camera clips
    camera_clips = relationship("CameraClip", back_populates="submission", cascade="all, delete-orphan")


class ExamSession(Base):
    """Tracks a student actively taking an exam (created on start, updated via heartbeat)."""
    __tablename__ = "exam_sessions"

    id = Column(String, primary_key=True, index=True)

    exam_id = Column(String, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    exam = relationship("Exam")

    student_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    student = relationship("User")

    student_id_number = Column(String, nullable=True)
    student_major = Column(String, nullable=True)

    started_at = Column(BigInteger, nullable=False)       # epoch ms
    last_heartbeat = Column(BigInteger, nullable=False)   # epoch ms
    tab_switches = Column(Integer, default=0)

    # 'active' → still taking | 'submitted' → done | 'abandoned' → no heartbeat
    status = Column(String, default="active", nullable=False)

    submission_id = Column(String, ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class CameraClip(Base):
    """Short (~5 s) WebM clip captured when a student looks down during an exam."""
    __tablename__ = "camera_clips"

    id = Column(String, primary_key=True, index=True)

    submission_id = Column(String, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    submission = relationship("Submission", back_populates="camera_clips")

    # Epoch ms of the look-down event on the client
    event_timestamp = Column(BigInteger, nullable=False)

    # Path relative to MEDIA_ROOT, e.g. "camera_clips/<submission_id>/<id>.webm"
    file_path = Column(String, nullable=False)

    # File size in bytes (handy for storage monitoring)
    file_size = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)