from pydantic import BaseModel, EmailStr, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# ============= User Schemas =============

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: str = Field(min_length=8)
    role: str = Field(default="student", pattern="^(student|teacher|admin)$")

class UserLogin(BaseModel):
    username: str
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    current_password: Optional[str] = None

class UserResponse(UserBase):
    id: str
    role: str
    created_at: datetime
    google_id: Optional[str] = None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# ============= Exam Schemas =============

class QuestionSchema(BaseModel):
    id: str
    type: str
    question: str
    points: int
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    code_template: Optional[str] = None
    starter_code: Optional[str] = None
    language: Optional[str] = None
    min_words: Optional[int] = None
    image_url: Optional[str] = None

class ExamBase(BaseModel):
    title: str
    description: str = ""
    questions: List[QuestionSchema]
    duration_minutes: int
    passing_score: int = 0
    max_tab_switches: int = 3
    auto_fail_on_cheat: bool = True
    tab_switch_deduct_points: int = 0
    shuffle_questions: bool = False
    show_results_immediately: bool = False

class ExamCreate(ExamBase):
    exam_code: Optional[str] = None

class ExamUpdate(ExamBase):
    status: Optional[str] = None
    exam_code: Optional[str] = None

class ExamResponse(ExamBase):
    id: str
    creator_id: str
    status: str
    exam_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ============= Submission Schemas =============

class SubmissionCreate(BaseModel):
    answers: Dict[str, str]
    tab_switches: int = 0
    behavior_score: int = 100
    start_time: int
    submit_time: int
    student_id_number: Optional[str] = None
    student_major: Optional[str] = None
    camera_events: Optional[List[Any]] = None  # accepted but ignored by backend

class SubmissionResponse(BaseModel):
    id: str
    student_id: str
    student_username: Optional[str] = None
    student_full_name: Optional[str] = None

    exam_id: str
    answers: Dict[str, str]
    tab_switches: int
    behavior_score: int
    status: str
    total_score: Optional[float] = None
    ai_grading_results: Optional[Dict[str, Any]] = None
    individual_scores: Optional[Dict[str, Any]] = None
    plagiarism_results: Optional[Dict[str, Any]] = None
    student_id_number: Optional[str] = None
    student_major: Optional[str] = None
    created_at: datetime

    @model_validator(mode='after')
    def populate_individual_scores(self):
        if self.individual_scores is None and self.ai_grading_results is not None:
            self.individual_scores = self.ai_grading_results
        return self

    class Config:
        from_attributes = True