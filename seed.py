from app.database import SessionLocal
from app import crud, schemas

db = SessionLocal()

try:
    # Check if users already exist
    existing_teacher = crud.get_user_by_username(db, "teacher1")
    if existing_teacher:
        print("⚠️ Users already exist. Skipping seed.")
        db.close()
        exit(0)

    # Create teacher
    teacher = schemas.UserCreate(
        username="teacher1",
        password="password123",
        role="teacher",
        full_name="John Teacher",
        email="teacher@example.com"
    )
    db_teacher = crud.create_user(db, teacher)
    print(f"✅ Created teacher: {db_teacher.username}")
    
    # Create student
    student = schemas.UserCreate(
        username="student1",
        password="password123",
        role="student",
        full_name="Jane Student",
        email="student@example.com"
    )
    db_student = crud.create_user(db, student)
    print(f"✅ Created student: {db_student.username}")
    
    print("\n🎉 Seed data created successfully!")
    print("\nLogin credentials:")
    print("  Teacher: teacher1 / password123")
    print("  Student: student1 / password123")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()