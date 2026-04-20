from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from typing import List

from .. import crud, schemas, models
from ..database import get_db
from .auth import get_current_user
from ..services.ai_service import grade_essay

router = APIRouter(prefix="/submissions", tags=["Submissions"])


def attach_username(submission: models.Submission) -> models.Submission:
    submission.student_username = (
        submission.student.username if submission.student else None
    )
    submission.student_full_name = (
        submission.student.full_name if submission.student else None
    )
    return submission


def instant_grade(exam: models.Exam, answers: dict) -> tuple:
    """
    Synchronously grades MC, true/false, short answer, and code questions.
    Essays are left as None — graded later by teacher or AI background task.
    Returns (individual_scores dict, partial_percentage or None).
    """
    individual_scores = {}
    scored_earned = 0
    scored_possible = 0

    for question in exam.questions:
        qid = question["id"]
        qtype = question["type"]
        max_pts = question["points"]
        student_ans = answers.get(qid, "")

        if qtype in ("multiple_choice", "true_false", "short_answer"):
            correct = (question.get("correct_answer") or "").strip().lower()
            given = (str(student_ans) if student_ans else "").strip().lower()
            is_correct = (given == correct) and (correct != "")
            score = max_pts if is_correct else 0
            individual_scores[qid] = {
                "score": score,
                "max_score": max_pts,
                "is_correct": is_correct,
                "feedback": None,
                "ai_detected": False,
                "ai_confidence": None,
            }
            scored_earned += score
            scored_possible += max_pts

        elif qtype == "code":
            # ran_ok is passed as a separate key alongside the answer
            ran_ok = bool(answers.get(f"{qid}_ran_ok", False))
            score = max_pts if ran_ok else 0
            individual_scores[qid] = {
                "score": score,
                "max_score": max_pts,
                "is_correct": ran_ok,
                "feedback": "Багш нэмэлт оноо өгч болно." if ran_ok else None,
                "ai_detected": False,
                "ai_confidence": None,
            }
            scored_earned += score
            scored_possible += max_pts

        elif qtype == "essay":
            # Unscored until teacher/AI grades it
            individual_scores[qid] = {
                "score": None,
                "max_score": max_pts,
                "is_correct": None,
                "feedback": None,
                "ai_detected": False,
                "ai_confidence": None,
            }
            # Essays intentionally excluded from scored_possible for now

    partial_pct = (scored_earned / scored_possible * 100) if scored_possible > 0 else None
    return individual_scores, partial_pct


def process_ai_grading(db: Session, submission_id: str, exam: models.Exam, answers: dict):
    """
    Background task — grades ONLY essay questions with AI.
    Merges results into the existing individual_scores and recalculates total_score.
    """
    submission = db.query(models.Submission).filter(
        models.Submission.id == submission_id
    ).first()
    if not submission:
        return

    existing_scores = dict(submission.individual_scores or {})
    total_max = 0
    total_earned = 0

    for question in exam.questions:
        qid = question["id"]
        max_pts = question["points"]
        total_max += max_pts

        if question["type"] == "essay" and qid in answers:
            result = grade_essay(
                question=question["question"],
                answer=answers[qid],
                max_points=max_pts,
            )
            existing_scores[qid] = {
                "score": result.get("score", 0),
                "max_score": max_pts,
                "is_correct": result.get("score", 0) >= max_pts * 0.7,
                "feedback": result.get("feedback", None),
                "ai_detected": result.get("ai_detected", False),
                "ai_confidence": result.get("ai_confidence", None),
            }
            total_earned += result.get("score", 0)
        else:
            # Non-essay: use the already-graded score
            total_earned += existing_scores.get(qid, {}).get("score", 0) or 0

    percentage = (total_earned / total_max * 100) if total_max > 0 else 0

    # Re-apply tab switch deduction after AI grading
    deduct_per_switch = getattr(exam, "tab_switch_deduct_points", 0) or 0
    if not exam.auto_fail_on_cheat and deduct_per_switch > 0:
        total_deduction = (submission.tab_switches or 0) * deduct_per_switch
        percentage = max(0.0, percentage - total_deduction)

    crud.update_submission_score(db, submission_id, percentage, existing_scores)


@router.post(
    "/exams/{exam_id}/submit",
    response_model=schemas.SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_exam(
    exam_id: str,
    submission: schemas.SubmissionCreate,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Only students can submit exams")

    exam = crud.get_exam(db, exam_id=exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    if exam.status != "published":
        raise HTTPException(status_code=400, detail="Exam not available")

    # Determine pass/fail/cheat status
    status_val = "completed"
    if submission.tab_switches >= exam.max_tab_switches and exam.auto_fail_on_cheat:
        status_val = "failed"

    # --- Normalize answers: frontend sends [{question_id, answer}], convert to dict ---
    if isinstance(submission.answers, list):
        answers_dict = {item["question_id"]: item["answer"] for item in submission.answers}
    else:
        answers_dict = submission.answers

    # --- Instant grading (sync, before saving) ---
    individual_scores, partial_score = instant_grade(exam, answers_dict)

    # --- Apply tab switch point deduction (when auto_fail_on_cheat is False) ---
    deduct_per_switch = getattr(exam, "tab_switch_deduct_points", 0) or 0
    if not exam.auto_fail_on_cheat and deduct_per_switch > 0 and partial_score is not None:
        total_deduction = submission.tab_switches * deduct_per_switch
        partial_score = max(0.0, partial_score - total_deduction)

    db_submission = crud.create_submission(
        db=db,
        submission=submission,
        exam_id=exam_id,
        user_id=current_user.id,
        status=status_val,
        individual_scores=individual_scores,
        total_score=partial_score,  # partial — essays not yet counted
    )

    # --- Essay AI grading (async background) ---
    has_essays = any(q["type"] == "essay" for q in exam.questions)
    if status_val == "completed" and has_essays:
        background_tasks.add_task(
            process_ai_grading,
            db,
            db_submission.id,
            exam,
            answers_dict,
        )

    # Re-fetch with student relationship
    db_submission = (
        db.query(models.Submission)
        .options(joinedload(models.Submission.student))
        .filter(models.Submission.id == db_submission.id)
        .first()
    )
    return attach_username(db_submission)


@router.get("/", response_model=List[schemas.SubmissionResponse])
def get_submissions(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submissions = crud.get_submissions(
        db, user_id=current_user.id, role=current_user.role
    )
    return [attach_username(s) for s in submissions]


@router.get("/{submission_id}", response_model=schemas.SubmissionResponse)
def get_submission(
    submission_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = (
        db.query(models.Submission)
        .options(joinedload(models.Submission.student))
        .filter(models.Submission.id == submission_id)
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if current_user.role == "student" and submission.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if current_user.role == "teacher":
        exam = crud.get_exam(db, submission.exam_id)
        if exam.creator_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return attach_username(submission)


@router.patch("/{submission_id}/score")
def update_score(
    submission_id: str,
    score_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can grade submissions")

    submission = (
        db.query(models.Submission)
        .options(joinedload(models.Submission.student))
        .filter(models.Submission.id == submission_id)
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    exam = crud.get_exam(db, exam_id=submission.exam_id)
    if exam.creator_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only grade submissions for your exams"
        )

    # Support updating individual question scores + recalculating total
    if "individual_scores" in score_data:
        updated_scores = dict(submission.individual_scores or {})
        updated_scores.update(score_data["individual_scores"])
        submission.individual_scores = updated_scores

        # Recalculate total from all scores that have a value
        total_max = sum(q["points"] for q in exam.questions)
        total_earned = sum(
            (v.get("score") or 0)
            for v in updated_scores.values()
            if v.get("score") is not None
        )
        submission.total_score = (total_earned / total_max * 100) if total_max > 0 else 0
    else:
        # Simple flat score override
        submission.total_score = float(score_data.get("score", score_data))

    db.commit()
    db.refresh(submission)
    return attach_username(submission)