#!/usr/bin/env python3
"""
Quick migration: Add student_id_number and student_major to submissions table.
"""
import os
import sys

# Add the app directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from app import models
from sqlalchemy import text

def run_migration():
    """Create all tables - SQLAlchemy will add the new columns"""
    print("Creating/updating database schema...")
    models.Base.metadata.create_all(bind=engine)
    print("✅ Database schema updated successfully!")

if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
