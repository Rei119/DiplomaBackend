from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .database import engine, Base
from .routers import auth, exams, submissions, ai_detect, users, camera_clips, sessions, monitor, question_images
from .services import scan
from .config import settings

Base.metadata.create_all(bind=engine)

def _migrate():
    """Add new columns to existing tables without Alembic."""
    migrations = [
        "ALTER TABLE submissions ADD COLUMN copy_paste_count INTEGER DEFAULT 0",
        "ALTER TABLE submissions ADD COLUMN fullscreen_exit_count INTEGER DEFAULT 0",
        "ALTER TABLE exam_sessions ADD COLUMN copy_paste_count INTEGER DEFAULT 0",
        "ALTER TABLE exam_sessions ADD COLUMN fullscreen_exit_count INTEGER DEFAULT 0",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()

try:
    _migrate()
except Exception:
    pass

app = FastAPI(
    title="Exam Platform API",
    description="AI-Powered Anti-Cheat Exam Platform",
    version="1.0.0"
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(exams.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(ai_detect.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(camera_clips.router, prefix="/api/submissions", tags=["camera-clips"])
app.include_router(sessions.router, prefix="/api")
app.include_router(question_images.router, prefix="/api")
app.include_router(monitor.router)   # WebSocket — no /api prefix (ws:// path)
app.include_router(scan.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Exam Platform API", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}