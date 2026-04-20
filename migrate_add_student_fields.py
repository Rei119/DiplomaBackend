"""
Migration script to add student_id_number and student_major columns to submissions table.
Run this once to update the schema.
"""
import os
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://examuser:exampass123@localhost:5432/examdb")

engine = create_engine(DATABASE_URL)

def migrate():
    with engine.begin() as conn:
        # Add columns if they don't exist
        try:
            conn.execute(text("""
                ALTER TABLE submissions
                ADD COLUMN IF NOT EXISTS student_id_number VARCHAR(255) DEFAULT NULL,
                ADD COLUMN IF NOT EXISTS student_major VARCHAR(255) DEFAULT NULL;
            """))
            print("✅ Migration successful: Added student_id_number and student_major columns")
        except Exception as e:
            print(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate()
