"""
Batch-enroll students from the performance prediction project.
Photos are taken from the facial rec project, sorted alphabetically,
and paired with students sorted by index number.

Run once from this directory:  python enroll_batch.py
"""

import os, json, uuid, sqlite3, shutil
import numpy as np
from deepface import DeepFace

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, 'attendance.db')
STUDENTS_FOLDER = os.path.join(BASE_DIR, 'uploads', 'students')

PERF_DB  = r'C:\Users\ericd\OneDrive\Desktop\FP\mini projects\perfromance prediction\attendance.db'
PHOTO_DIR = r'C:\Users\ericd\OneDrive\Desktop\FP\mini projects\facial rec'

MODEL_NAME       = 'VGG-Face'
DETECTOR_BACKEND = 'opencv'

ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

os.makedirs(STUDENTS_FOLDER, exist_ok=True)


# ── Init integration DB (safe to run if tables already exist) ──────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS students (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL UNIQUE,
            index_number TEXT    NOT NULL UNIQUE,
            photo_path   TEXT    NOT NULL,
            embedding    TEXT    NOT NULL,
            enrolled_at  TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS class_students (
            class_id   INTEGER NOT NULL REFERENCES classes(id)  ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            PRIMARY KEY (class_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            title TEXT NOT NULL, date TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            photo_path TEXT, annotated_path TEXT, total_faces INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id)  ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES students(id)  ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'present',
            confidence REAL,
            logged_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(session_id, student_id)
        );
    ''')
    conn.commit()
    conn.close()


def cosine_dist(a, b):
    a, b = np.array(a, dtype=np.float64), np.array(b, dtype=np.float64)
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return 1.0 if n == 0 else 1.0 - np.dot(a, b) / n


def main():
    init_db()

    # ── Collect photo files (name-based only, no group shots) ──────────────────
    excluded = {'10-under-10-Featured-Image-800x400.jpg', 'part left.png'}
    photos = sorted(
        [f for f in os.listdir(PHOTO_DIR)
         if os.path.splitext(f)[1].lower() in ALLOWED_EXT and f not in excluded],
        key=str.lower
    )

    # ── Fetch students sorted by index number ──────────────────────────────────
    src = sqlite3.connect(PERF_DB)
    src.row_factory = sqlite3.Row
    students = src.execute('SELECT * FROM students ORDER BY index_number').fetchall()
    src.close()

    if len(photos) != len(students):
        print(f'WARNING: {len(photos)} photos but {len(students)} students — will enroll {min(len(photos), len(students))} pairs.')

    pairs = list(zip(students, photos))

    print(f'\nEnrolling {len(pairs)} students...')
    print('=' * 55)
    print(f'{"Photo":<20}  {"Student":<20}  {"Index"}')
    print('-' * 55)
    for s, p in pairs:
        print(f'{p:<20}  {s["name"]:<20}  {s["index_number"]}')
    print('=' * 55)
    print()

    dest_conn = sqlite3.connect(DB_PATH)
    dest_conn.execute('PRAGMA foreign_keys = ON')

    ok, skipped, failed = 0, 0, 0

    for student, photo_filename in pairs:
        name         = student['name']
        index_number = student['index_number']
        src_path     = os.path.join(PHOTO_DIR, photo_filename)
        ext          = os.path.splitext(photo_filename)[1].lower()

        print(f'  [{index_number}] {name}  ({photo_filename})')

        # Check for existing
        existing = dest_conn.execute(
            'SELECT id FROM students WHERE index_number=? OR name=?',
            (index_number, name)
        ).fetchone()
        if existing:
            print(f'        -> SKIPPED (already enrolled)')
            skipped += 1
            continue

        # Copy photo to uploads/students
        dest_filename = f'{uuid.uuid4()}{ext}'
        dest_path     = os.path.join(STUDENTS_FOLDER, dest_filename)
        shutil.copy2(src_path, dest_path)

        # Run DeepFace
        try:
            reps = DeepFace.represent(
                img_path=dest_path,
                model_name=MODEL_NAME,
                detector_backend=DETECTOR_BACKEND,
                enforce_detection=True,
                align=True,
            )
            if not reps:
                raise ValueError('No face detected')
            embedding = reps[0]['embedding']
        except Exception as exc:
            os.remove(dest_path)
            print(f'        -> FAILED: {exc}')
            failed += 1
            continue

        # Insert into DB
        try:
            dest_conn.execute(
                'INSERT INTO students (name, index_number, photo_path, embedding) VALUES (?,?,?,?)',
                (name, index_number, f'students/{dest_filename}', json.dumps(embedding))
            )
            dest_conn.commit()
            print(f'        -> OK')
            ok += 1
        except sqlite3.IntegrityError as exc:
            os.remove(dest_path)
            print(f'        -> SKIPPED (duplicate: {exc})')
            skipped += 1

    dest_conn.close()

    print()
    print('=' * 55)
    print(f'Done.  Enrolled: {ok}   Skipped: {skipped}   Failed: {failed}')
    print('You can now open http://localhost:5000 and take attendance.')
    print('=' * 55)


if __name__ == '__main__':
    main()
