import os
import json
import sqlite3
import uuid
import numpy as np
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from deepface import DeepFace
import cv2

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'attendlog-dev-key-change-in-production')

MODEL_NAME       = 'VGG-Face'
DETECTOR_BACKEND = 'opencv'
THRESHOLD        = 0.40

UPLOAD_FOLDER   = 'uploads'
STUDENTS_FOLDER = os.path.join(UPLOAD_FOLDER, 'students')
SESSIONS_FOLDER = os.path.join(UPLOAD_FOLDER, 'sessions')
DB_PATH         = 'attendance.db'

os.makedirs(STUDENTS_FOLDER, exist_ok=True)
os.makedirs(SESSIONS_FOLDER, exist_ok=True)

ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}


# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS teachers (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS students (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL UNIQUE,
                index_number TEXT    NOT NULL UNIQUE,
                photo_path   TEXT    NOT NULL,
                embedding    TEXT    NOT NULL,
                teacher_id   INTEGER REFERENCES teachers(id),
                enrolled_at  TEXT    DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS classes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                description TEXT,
                teacher_id  INTEGER REFERENCES teachers(id),
                created_at  TEXT    DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS class_students (
                class_id   INTEGER NOT NULL REFERENCES classes(id)  ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                PRIMARY KEY (class_id, student_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                title          TEXT    NOT NULL,
                date           TEXT    NOT NULL,
                weight         REAL    DEFAULT 1.0,
                photo_path     TEXT,
                annotated_path TEXT,
                total_faces    INTEGER DEFAULT 0,
                created_at     TEXT    DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id)  ON DELETE CASCADE,
                student_id INTEGER NOT NULL REFERENCES students(id)  ON DELETE CASCADE,
                status     TEXT    NOT NULL DEFAULT 'present',
                confidence REAL,
                logged_at  TEXT    DEFAULT (datetime('now','localtime')),
                UNIQUE(session_id, student_id)
            );
        ''')

        # Migration: add teacher_id to existing tables if not present
        for sql in [
            'ALTER TABLE students ADD COLUMN teacher_id INTEGER REFERENCES teachers(id)',
            'ALTER TABLE classes  ADD COLUMN teacher_id INTEGER REFERENCES teachers(id)',
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        conn.commit()

        # Seed admin123 account and claim any pre-existing data
        admin = conn.execute("SELECT id FROM teachers WHERE username='admin123'").fetchone()
        if not admin:
            cur = conn.execute(
                'INSERT INTO teachers (username, password_hash) VALUES (?, ?)',
                ('admin123', generate_password_hash('admin123'))
            )
            admin_id = cur.lastrowid
            conn.commit()
        else:
            admin_id = admin['id']

        conn.execute('UPDATE students SET teacher_id=? WHERE teacher_id IS NULL', (admin_id,))
        conn.execute('UPDATE classes  SET teacher_id=? WHERE teacher_id IS NULL', (admin_id,))
        conn.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def cosine_dist(a, b):
    a, b = np.array(a, dtype=np.float64), np.array(b, dtype=np.float64)
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return 1.0 if n == 0 else 1.0 - np.dot(a, b) / n


def safe_remove(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ── Auth ───────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'teacher_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET'])
def login_page():
    if 'teacher_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/signup', methods=['GET'])
def signup_page():
    if 'teacher_id' in session:
        return redirect(url_for('index'))
    return render_template('signup.html')


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data     = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    with get_db() as conn:
        teacher = conn.execute('SELECT * FROM teachers WHERE username=?', (username,)).fetchone()
    if not teacher or not check_password_hash(teacher['password_hash'], password):
        return jsonify({'error': 'Invalid username or password'}), 401
    session['teacher_id'] = teacher['id']
    session['username']   = teacher['username']
    return jsonify({'ok': True})


@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data     = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    try:
        with get_db() as conn:
            cur = conn.execute(
                'INSERT INTO teachers (username, password_hash) VALUES (?, ?)',
                (username, generate_password_hash(password))
            )
            tid = cur.lastrowid
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': f'Username "{username}" is already taken'}), 409
    session['teacher_id'] = tid
    session['username']   = username
    return jsonify({'ok': True})


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


# ── Static / Index ─────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session['username'])


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ── Students ───────────────────────────────────────────────────────────────────

@app.route('/api/students', methods=['GET'])
@login_required
def list_students():
    tid = session['teacher_id']
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, name, index_number, photo_path, enrolled_at FROM students WHERE teacher_id=? ORDER BY name',
            (tid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/students/enroll', methods=['POST'])
@login_required
def enroll():
    tid          = session['teacher_id']
    name         = request.form.get('name', '').strip()
    index_number = request.form.get('index_number', '').strip()
    photo        = request.files.get('photo')

    if not name:         return jsonify({'error': 'Student name is required'}), 400
    if not index_number: return jsonify({'error': 'Index number is required'}), 400
    if not photo:        return jsonify({'error': 'Photo is required'}), 400

    ext = os.path.splitext(photo.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({'error': f'Unsupported file type "{ext}"'}), 400

    filename = f"{uuid.uuid4()}{ext}"
    abs_path = os.path.join(STUDENTS_FOLDER, filename)
    photo.save(abs_path)

    try:
        reps = DeepFace.represent(
            img_path=abs_path,
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=True,
            align=True,
        )
        if not reps:
            raise ValueError('No face detected in photo')
        embedding = reps[0]['embedding']
    except Exception as exc:
        safe_remove(abs_path)
        return jsonify({'error': f'Face detection failed: {exc}'}), 422

    try:
        with get_db() as conn:
            cur = conn.execute(
                'INSERT INTO students (name, index_number, photo_path, embedding, teacher_id) VALUES (?, ?, ?, ?, ?)',
                (name, index_number, f'students/{filename}', json.dumps(embedding), tid),
            )
            sid = cur.lastrowid
            conn.commit()
    except sqlite3.IntegrityError as exc:
        safe_remove(abs_path)
        msg = str(exc).lower()
        if 'name' in msg:
            return jsonify({'error': f'A student named "{name}" is already enrolled'}), 409
        return jsonify({'error': f'Index number "{index_number}" is already registered'}), 409

    return jsonify({
        'id': sid, 'name': name,
        'index_number': index_number,
        'photo_path': f'students/{filename}',
    })


@app.route('/api/students/<int:sid>', methods=['DELETE'])
@login_required
def delete_student(sid):
    tid = session['teacher_id']
    with get_db() as conn:
        row = conn.execute('SELECT photo_path FROM students WHERE id=? AND teacher_id=?', (sid, tid)).fetchone()
        if not row:
            return jsonify({'error': 'Student not found'}), 404
        conn.execute('DELETE FROM students WHERE id=?', (sid,))
        conn.commit()
    safe_remove(os.path.join(UPLOAD_FOLDER, row['photo_path'].replace('/', os.sep)))
    return jsonify({'ok': True})


# ── Classes ────────────────────────────────────────────────────────────────────

@app.route('/api/classes', methods=['GET'])
@login_required
def list_classes():
    tid = session['teacher_id']
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM classes WHERE teacher_id=? ORDER BY created_at DESC', (tid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/classes', methods=['POST'])
@login_required
def create_class():
    tid  = session['teacher_id']
    data = request.get_json()
    name = (data.get('name') or '').strip()
    desc = (data.get('description') or '').strip()
    if not name:
        return jsonify({'error': 'Class name is required'}), 400
    with get_db() as conn:
        cur = conn.execute('INSERT INTO classes (name, description, teacher_id) VALUES (?, ?, ?)', (name, desc, tid))
        cid = cur.lastrowid
        conn.commit()
    return jsonify({'id': cid, 'name': name, 'description': desc})


@app.route('/api/classes/<int:cid>', methods=['DELETE'])
@login_required
def delete_class(cid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        conn.execute('DELETE FROM classes WHERE id=?', (cid,))
        conn.commit()
    return jsonify({'ok': True})


@app.route('/api/classes/<int:cid>/students', methods=['GET'])
@login_required
def class_students(cid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        rows = conn.execute('''
            SELECT s.id, s.name, s.index_number, s.photo_path
            FROM students s
            JOIN class_students cs ON cs.student_id = s.id
            WHERE cs.class_id = ? ORDER BY s.name
        ''', (cid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/classes/<int:cid>/students', methods=['POST'])
@login_required
def add_to_class(cid):
    tid  = session['teacher_id']
    data = request.get_json()
    sid  = data.get('student_id')
    if not sid:
        return jsonify({'error': 'student_id required'}), 400
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        try:
            conn.execute('INSERT INTO class_students (class_id, student_id) VALUES (?, ?)', (cid, sid))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Student already in this class'}), 409
    return jsonify({'ok': True})


@app.route('/api/classes/<int:cid>/students/<int:sid>', methods=['DELETE'])
@login_required
def remove_from_class(cid, sid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        conn.execute('DELETE FROM class_students WHERE class_id=? AND student_id=?', (cid, sid))
        conn.commit()
    return jsonify({'ok': True})


# ── Sessions ───────────────────────────────────────────────────────────────────

@app.route('/api/sessions', methods=['GET'])
@login_required
def all_sessions():
    tid      = session['teacher_id']
    class_id = request.args.get('class_id')
    with get_db() as conn:
        if class_id:
            rows = conn.execute('''
                SELECT s.id, s.title, s.date, s.weight, s.photo_path, s.annotated_path,
                       s.total_faces, s.created_at, c.name AS class_name, c.id AS class_id,
                       COUNT(a.id) AS present_count
                FROM sessions s
                JOIN classes c ON c.id = s.class_id
                LEFT JOIN attendance a ON a.session_id = s.id
                WHERE s.class_id = ? AND c.teacher_id = ?
                GROUP BY s.id ORDER BY s.created_at DESC
            ''', (class_id, tid)).fetchall()
        else:
            rows = conn.execute('''
                SELECT s.id, s.title, s.date, s.weight, s.photo_path, s.annotated_path,
                       s.total_faces, s.created_at, c.name AS class_name, c.id AS class_id,
                       COUNT(a.id) AS present_count
                FROM sessions s
                JOIN classes c ON c.id = s.class_id
                LEFT JOIN attendance a ON a.session_id = s.id
                WHERE c.teacher_id = ?
                GROUP BY s.id ORDER BY s.created_at DESC
            ''', (tid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/classes/<int:cid>/sessions', methods=['GET'])
@login_required
def list_sessions(cid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        rows = conn.execute('''
            SELECT s.id, s.title, s.date, s.weight, s.photo_path, s.annotated_path,
                   s.total_faces, s.created_at, COUNT(a.id) AS present_count
            FROM sessions s
            LEFT JOIN attendance a ON a.session_id = s.id
            WHERE s.class_id = ? GROUP BY s.id ORDER BY s.date DESC
        ''', (cid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/classes/<int:cid>/sessions', methods=['POST'])
@login_required
def create_session(cid):
    tid    = session['teacher_id']
    data   = request.get_json()
    title  = (data.get('title') or '').strip()
    date   = (data.get('date') or '').strip()
    weight = float(data.get('weight') or 1.0)
    if not title or not date:
        return jsonify({'error': 'Title and date required'}), 400
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        cur = conn.execute(
            'INSERT INTO sessions (class_id, title, date, weight) VALUES (?,?,?,?)',
            (cid, title, date, weight)
        )
        sess_id = cur.lastrowid
        conn.commit()
    return jsonify({'id': sess_id, 'title': title, 'date': date, 'weight': weight})


@app.route('/api/sessions/<int:sid>', methods=['GET'])
@login_required
def get_session(sid):
    tid = session['teacher_id']
    with get_db() as conn:
        sess = conn.execute('''
            SELECT s.* FROM sessions s
            JOIN classes c ON c.id = s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone()
        if not sess:
            return jsonify({'error': 'Not found'}), 404
        records = conn.execute('''
            SELECT s.id, s.name, s.index_number, s.photo_path, a.confidence, a.logged_at
            FROM attendance a JOIN students s ON s.id=a.student_id
            WHERE a.session_id=? ORDER BY s.name
        ''', (sid,)).fetchall()
    return jsonify({**dict(sess), 'records': [dict(r) for r in records]})


@app.route('/api/sessions/<int:sid>', methods=['PUT'])
@login_required
def update_session(sid):
    tid    = session['teacher_id']
    data   = request.get_json()
    title  = (data.get('title') or '').strip()
    date   = (data.get('date') or '').strip()
    weight = float(data.get('weight') or 1.0)
    if not title or not date:
        return jsonify({'error': 'Title and date required'}), 400
    with get_db() as conn:
        if not conn.execute('''
            SELECT s.id FROM sessions s JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone():
            return jsonify({'error': 'Session not found'}), 404
        conn.execute('UPDATE sessions SET title=?,date=?,weight=? WHERE id=?', (title, date, weight, sid))
        conn.commit()
    return jsonify({'ok': True})


@app.route('/api/sessions/<int:sid>', methods=['DELETE'])
@login_required
def delete_session(sid):
    tid = session['teacher_id']
    with get_db() as conn:
        sess = conn.execute('''
            SELECT s.photo_path, s.annotated_path FROM sessions s
            JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone()
        if not sess:
            return jsonify({'error': 'Not found'}), 404
        conn.execute('DELETE FROM sessions WHERE id=?', (sid,))
        conn.commit()
    for rel in [sess['photo_path'], sess['annotated_path']]:
        if rel:
            safe_remove(os.path.join(UPLOAD_FOLDER, rel.replace('/', os.sep)))
    return jsonify({'ok': True})


# ── Attendance ─────────────────────────────────────────────────────────────────

@app.route('/api/sessions/<int:sid>/attendance', methods=['GET'])
@login_required
def session_attendance(sid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('''
            SELECT s.id FROM sessions s JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone():
            return jsonify({'error': 'Session not found'}), 404
        rows = conn.execute('''
            SELECT a.id, a.status, a.confidence, a.logged_at,
                   s.id AS student_id, s.name, s.name AS student_name,
                   s.index_number, s.photo_path
            FROM attendance a JOIN students s ON s.id=a.student_id
            WHERE a.session_id=? ORDER BY a.logged_at DESC
        ''', (sid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/sessions/<int:sid>/mark', methods=['POST'])
@login_required
def mark_attendance(sid):
    tid          = session['teacher_id']
    data         = request.get_json()
    index_number = (data.get('index_number') or '').strip()
    if not index_number:
        return jsonify({'error': 'index_number required'}), 400

    with get_db() as conn:
        sess = conn.execute('''
            SELECT s.class_id FROM sessions s JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone()
        if not sess:
            return jsonify({'error': 'Session not found'}), 404

        student = conn.execute(
            'SELECT * FROM students WHERE index_number=? AND teacher_id=?',
            (index_number, tid)
        ).fetchone()
        if not student:
            return jsonify({'error': f'No student with index number "{index_number}"'}), 404

        if not conn.execute(
            'SELECT 1 FROM class_students WHERE class_id=? AND student_id=?',
            (sess['class_id'], student['id'])
        ).fetchone():
            return jsonify({'error': f'{student["name"]} is not enrolled in this class'}), 403

        if conn.execute(
            'SELECT 1 FROM attendance WHERE session_id=? AND student_id=?',
            (sid, student['id'])
        ).fetchone():
            return jsonify({'error': f'{student["name"]} is already marked present', 'student': dict(student)}), 409

        conn.execute(
            'INSERT INTO attendance (session_id, student_id, status) VALUES (?,?,?)',
            (sid, student['id'], 'present')
        )
        conn.commit()

    return jsonify({'ok': True, 'student': dict(student)})


@app.route('/api/sessions/<int:sid>/face-attend', methods=['POST'])
@login_required
def face_attend(sid):
    tid   = session['teacher_id']
    photo = request.files.get('photo')
    if not photo:
        return jsonify({'error': 'Group photo is required'}), 400

    with get_db() as conn:
        sess = conn.execute('''
            SELECT s.class_id FROM sessions s JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone()
        if not sess:
            return jsonify({'error': 'Session not found'}), 404
        class_id = sess['class_id']
        students = conn.execute('''
            SELECT s.id, s.name, s.index_number, s.embedding
            FROM students s JOIN class_students cs ON cs.student_id=s.id
            WHERE cs.class_id=?
        ''', (class_id,)).fetchall()

    if not students:
        return jsonify({'error': 'No students enrolled in this class yet'}), 400

    ext      = os.path.splitext(photo.filename)[1].lower() or '.jpg'
    filename = f"{uuid.uuid4()}{ext}"
    abs_path = os.path.join(SESSIONS_FOLDER, filename)
    photo.save(abs_path)

    try:
        try:
            group_reps = DeepFace.represent(
                img_path=abs_path,
                model_name=MODEL_NAME,
                detector_backend=DETECTOR_BACKEND,
                enforce_detection=True,
                align=True,
            )
        except Exception:
            group_reps = []

        if not group_reps:
            safe_remove(abs_path)
            return jsonify({'error': 'No faces detected in the photo'}), 422

        student_data = [
            {'id': s['id'], 'name': s['name'], 'index_number': s['index_number'],
             'emb': json.loads(s['embedding'])}
            for s in students
        ]

        face_results = []
        best_per_student: dict[int, dict] = {}

        for face in group_reps:
            emb  = face['embedding']
            area = face.get('facial_area', {})
            best_dist, best_student = float('inf'), None
            for s in student_data:
                d = cosine_dist(emb, s['emb'])
                if d < best_dist:
                    best_dist, best_student = d, s

            if best_dist <= THRESHOLD and best_student:
                conf = round((1 - best_dist) * 100, 1)
                face_results.append({
                    'recognized': True, 'student_id': best_student['id'],
                    'name': best_student['name'], 'confidence': conf, 'area': area,
                })
                s_id = best_student['id']
                if s_id not in best_per_student or conf > best_per_student[s_id]['confidence']:
                    best_per_student[s_id] = {
                        'student_id': s_id, 'name': best_student['name'],
                        'index_number': best_student['index_number'], 'confidence': conf,
                    }
            else:
                face_results.append({'recognized': False, 'name': 'Unknown', 'confidence': 0, 'area': area})

        # Annotate image
        img = cv2.imread(abs_path)
        ann_rel = f'sessions/{filename}'
        if img is not None:
            h_img, w_img = img.shape[:2]
            lw        = max(2, w_img // 400)
            font_sz   = max(0.4, w_img / 1200)
            thickness = max(1, w_img // 600)
            for r in face_results:
                a = r['area']
                x, y, w, h = (a.get(k, 0) for k in ('x', 'y', 'w', 'h'))
                if not w or not h:
                    continue
                color = (34, 197, 94) if r['recognized'] else (68, 68, 239)
                cv2.rectangle(img, (x, y), (x + w, y + h), color, lw)
                label = f"{r['name']} {r['confidence']}%" if r['recognized'] else 'Unknown'
                tsz, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_sz, thickness)
                ly = max(tsz[1] + 4, y - 4)
                cv2.rectangle(img, (x, ly - tsz[1] - 4), (x + tsz[0] + 4, ly + 2), color, -1)
                cv2.putText(img, label, (x + 2, ly - 2),
                            cv2.FONT_HERSHEY_SIMPLEX, font_sz, (255, 255, 255), thickness)
            ann_filename = f"ann_{filename}"
            ann_abs      = os.path.join(SESSIONS_FOLDER, ann_filename)
            cv2.imwrite(ann_abs, img)
            ann_rel = f'sessions/{ann_filename}'

        with get_db() as conn:
            conn.execute(
                'UPDATE sessions SET photo_path=?,annotated_path=?,total_faces=? WHERE id=?',
                (f'sessions/{filename}', ann_rel, len(group_reps), sid)
            )
            marked, skipped = [], []
            for s_id, info in best_per_student.items():
                if not conn.execute(
                    'SELECT 1 FROM attendance WHERE session_id=? AND student_id=?', (sid, s_id)
                ).fetchone():
                    conn.execute(
                        'INSERT INTO attendance (session_id,student_id,status,confidence) VALUES (?,?,?,?)',
                        (sid, s_id, 'present', info['confidence'])
                    )
                    marked.append(info)
                else:
                    skipped.append(info)
            conn.commit()

        return jsonify({
            'total_faces':     len(group_reps),
            'marked':          marked,
            'skipped':         skipped,
            'unknown_count':   sum(1 for r in face_results if not r['recognized']),
            'annotated_photo': ann_rel,
            'face_results':    face_results,
        })

    except Exception as exc:
        safe_remove(abs_path)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/sessions/<int:sid>/attendance/<int:student_id>', methods=['DELETE'])
@login_required
def remove_attendance(sid, student_id):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('''
            SELECT s.id FROM sessions s JOIN classes c ON c.id=s.class_id
            WHERE s.id=? AND c.teacher_id=?
        ''', (sid, tid)).fetchone():
            return jsonify({'error': 'Session not found'}), 404
        conn.execute('DELETE FROM attendance WHERE session_id=? AND student_id=?', (sid, student_id))
        conn.commit()
    return jsonify({'ok': True})


# ── Analytics ──────────────────────────────────────────────────────────────────

@app.route('/api/classes/<int:cid>/analytics', methods=['GET'])
@login_required
def analytics(cid):
    tid = session['teacher_id']
    with get_db() as conn:
        if not conn.execute('SELECT id FROM classes WHERE id=? AND teacher_id=?', (cid, tid)).fetchone():
            return jsonify({'error': 'Class not found'}), 404
        students = conn.execute('''
            SELECT s.id, s.name, s.index_number, s.photo_path
            FROM students s JOIN class_students cs ON cs.student_id=s.id
            WHERE cs.class_id=? ORDER BY s.name
        ''', (cid,)).fetchall()
        sessions = conn.execute(
            'SELECT id, title, date, weight FROM sessions WHERE class_id=? ORDER BY date ASC', (cid,)
        ).fetchall()

        att_rows = []
        if sessions:
            ids = [s['id'] for s in sessions]
            att_rows = conn.execute(
                f"SELECT session_id, student_id, confidence FROM attendance WHERE session_id IN ({','.join('?'*len(ids))})",
                ids
            ).fetchall()

    att_map = {(r['session_id'], r['student_id']): r['confidence'] for r in att_rows}

    result = []
    for student in students:
        records, total_w, present_w = [], 0, 0
        for sess in sessions:
            is_present = (sess['id'], student['id']) in att_map
            records.append({
                'session':    dict(sess),
                'status':     'present' if is_present else 'absent',
                'confidence': att_map.get((sess['id'], student['id'])),
            })
            total_w += sess['weight']
            if is_present:
                present_w += sess['weight']

        rate = round((present_w / total_w) * 100, 1) if total_w > 0 else None

        consec = 0
        for r in reversed(records):
            if r['status'] == 'absent':
                consec += 1
            else:
                break

        flags = []
        if rate is not None and rate < 50:
            flags.append({'type': 'low_attendance', 'message': f'{rate}% — below 50%'})
        if consec >= 2:
            flags.append({'type': 'consecutive', 'message': f'{consec} consecutive absences'})

        result.append({
            'student':       dict(student),
            'rate':          rate,
            'currentConsec': consec,
            'flags':         flags,
            'records':       records,
        })

    return jsonify({'students': result, 'sessions': [dict(s) for s in sessions]})


# ── Boot ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print('\n' + '='*60)
    print('  Attendance + Facial Recognition System')
    print('='*60)
    print('  Open http://localhost:5000 in your browser')
    print('  Login: admin123 / admin123')
    print('  NOTE: First run downloads the face model (~500 MB)')
    print('='*60 + '\n')
    app.run(debug=True, port=5000, use_reloader=False)
