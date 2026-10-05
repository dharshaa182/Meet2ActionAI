import os
import re
import sqlite3
from datetime import datetime
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template,
    flash
)
from werkzeug.utils import secure_filename

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "meet2actionai-secret-key"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "meet2action.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


# =========================================================
# WHISPER MODEL
# =========================================================

whisper_model = None


def get_whisper_model():
    global whisper_model

    if whisper_model is None:

        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper is not installed."
            )

        print("Loading Whisper model...")

        whisper_model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1
        )

        print("Whisper model loaded successfully.")

    return whisper_model


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # Meetings
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            transcript TEXT,
            summary TEXT,
            participants TEXT,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # Tasks
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            task TEXT,
            owner TEXT,
            deadline TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TEXT,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id)
        )
    """)

    # -----------------------------------------------------
    # Problems
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            problem TEXT,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # Safe migration for old meetings database
    # -----------------------------------------------------

    meeting_columns = [
        row["name"]
        for row in cur.execute(
            "PRAGMA table_info(meetings)"
        ).fetchall()
    ]

    if "participants" not in meeting_columns:
        try:
            cur.execute(
                "ALTER TABLE meetings ADD COLUMN participants TEXT"
            )
        except Exception as e:
            print(
                "Participants migration warning:",
                repr(e)
            )

    if "created_at" not in meeting_columns:
        try:
            cur.execute(
                "ALTER TABLE meetings ADD COLUMN created_at TEXT"
            )
        except Exception as e:
            print(
                "Meeting created_at migration warning:",
                repr(e)
            )

    # -----------------------------------------------------
    # Task migrations
    # -----------------------------------------------------

    task_columns = [
        row["name"]
        for row in cur.execute(
            "PRAGMA table_info(tasks)"
        ).fetchall()
    ]

    if "meeting_id" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN meeting_id INTEGER"
            )
        except Exception as e:
            print(
                "Task meeting_id migration warning:",
                repr(e)
            )

    if "created_at" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN created_at TEXT"
            )
        except Exception as e:
            print(
                "Task created_at migration warning:",
                repr(e)
            )

    if "priority" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN priority TEXT"
            )
        except Exception as e:
            print(
                "Task priority migration warning:",
                repr(e)
            )

    if "status" not in task_columns:
        try:
            cur.execute(
                "ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'Pending'"
            )
        except Exception as e:
            print(
                "Task status migration warning:",
                repr(e)
            )

    # -----------------------------------------------------
    # Existing NULL participants safety
    # -----------------------------------------------------

    try:
        cur.execute("""
            UPDATE meetings
            SET participants = ''
            WHERE participants IS NULL
        """)
    except Exception as e:
        print(
            "Participants cleanup warning:",
            repr(e)
        )

    # -----------------------------------------------------
    # Existing NULL status safety
    # -----------------------------------------------------

    try:
        cur.execute("""
            UPDATE tasks
            SET status = 'Pending'
            WHERE status IS NULL OR status = ''
        """)
    except Exception as e:
        print(
            "Task status cleanup warning:",
            repr(e)
        )

    conn.commit()
    conn.close()


# =========================================================
# FILE VALIDATION
# =========================================================

ALLOWED_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "mp4",
    "mpeg",
    "mpga",
    "webm",
    "ogg",
    "flac"
}


def allowed_file(filename):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_EXTENSIONS


# =========================================================
# SUMMARY
# =========================================================

def generate_summary(transcript):

    if not transcript:
        return "No transcript available."

    text = re.sub(
        r"\s+",
        " ",
        transcript
    ).strip()

    if len(text) <= 500:
        return text

    return text[:500].rstrip() + "..."


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def clean_text(text):

    if not text:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def normalize_task(task):

    task = clean_text(task)

    # Remove self assignment prefix
    task = re.sub(
        r"^(?:"
        r"i\s+(?:will|shall|can|am going to)\s+|"
        r"we\s+(?:will|shall|can|are going to)\s+|"
        r"they\s+(?:will|shall|can|are going to)\s+|"
        r"you\s+(?:will|shall|can|are going to)\s+"
        r")",
        "",
        task,
        flags=re.I
    )

    # Remove named-person assignment prefix
    task = re.sub(
        r"^[A-Za-z][A-Za-z0-9_-]*\s+"
        r"(?:will|shall|can|is going to|has to|needs to|must)\s+",
        "",
        task,
        flags=re.I
    )

    # Remove common task prefixes
    task = re.sub(
        r"^(?:"
        r"we need to|"
        r"we have to|"
        r"we must|"
        r"need to|"
        r"needs to|"
        r"has to|"
        r"have to|"
        r"must|"
        r"should"
        r")\s+",
        "",
        task,
        flags=re.I
    )

    task = re.sub(
        r"^[,:;\-\s]+",
        "",
        task
    )

    if task:
        task = task[0].upper() + task[1:]

    return task.strip()


# =========================================================
# OWNER DETECTION
# =========================================================

KNOWN_NAMES = {
    "dharshan": "Dharshan",
    "mubeen": "Mubeen",
    "bala": "Bala",
    "pugazhendhi": "Pugazhendhi",
    "naveen": "Naveen",
    "arun": "Arun",
    "kumar": "Kumar",
    "priya": "Priya",
    "kamali": "Kamali"
}


def detect_owner(sentence):

    text = clean_text(sentence)

    # Self assignment
    if re.search(
        r"\bI\s+(?:will|shall|can|am going to)\b",
        text,
        flags=re.I
    ):
        return "Self"

    # Team assignment
    if re.search(
        r"\b(?:we|our team|the team)\s+"
        r"(?:will|shall|can|are going to)\b",
        text,
        flags=re.I
    ):
        return "Team"

    # Known names
    for name_key, display_name in KNOWN_NAMES.items():

        pattern = (
            r"\b"
            + re.escape(name_key)
            + r"\b\s+"
            r"(?:will|shall|can|is going to|has to|needs to|must)"
        )

        if re.search(
            pattern,
            text,
            flags=re.I
        ):
            return display_name

    # Generic named person
    match = re.search(
        r"\b([A-Z][a-z]{2,})\s+"
        r"(?:will|shall|can|is going to|has to|needs to|must)\b",
        text
    )

    if match:
        return match.group(1)

    # Assigned to / responsible for
    match = re.search(
        r"(?:assigned to|responsible for)\s+"
        r"([A-Z][a-z]{2,})",
        text,
        flags=re.I
    )

    if match:
        return match.group(1).title()

    return "Unassigned"


# =========================================================
# DEADLINE DETECTION
# =========================================================

WEEKDAYS = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday"
}


def detect_deadline(sentence):

    text = clean_text(sentence)

    if re.search(r"\btoday\b", text, re.I):
        return "Today"

    if re.search(r"\btomorrow\b", text, re.I):
        return "Tomorrow"

    if re.search(r"\btonight\b", text, re.I):
        return "Tonight"

    if re.search(r"\bthis week\b", text, re.I):
        return "This week"

    if re.search(r"\bnext week\b", text, re.I):
        return "Next week"

    weekday_pattern = (
        r"\b(?:by|before|on)?\s*"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    )

    match = re.search(
        weekday_pattern,
        text,
        flags=re.I
    )

    if match:
        return WEEKDAYS[
            match.group(1).lower()
        ]

    month_pattern = (
        r"\b("
        r"january|february|march|april|may|june|"
        r"july|august|september|october|november|december"
        r")\s+"
        r"(\d{1,2})"
        r"(?:st|nd|rd|th)?"
        r"(?:\s*,?\s*(\d{4}))?\b"
    )

    match = re.search(
        month_pattern,
        text,
        flags=re.I
    )

    if match:

        month = match.group(1).title()
        day = match.group(2)
        year = match.group(3)

        if year:
            return f"{month} {day}, {year}"

        return f"{month} {day}"

    reverse_month_pattern = (
        r"\b(\d{1,2})\s+"
        r"(january|february|march|april|may|june|"
        r"july|august|september|october|november|december)"
        r"(?:\s*,?\s*(\d{4}))?\b"
    )

    match = re.search(
        reverse_month_pattern,
        text,
        flags=re.I
    )

    if match:

        day = match.group(1)
        month = match.group(2).title()
        year = match.group(3)

        if year:
            return f"{month} {day}, {year}"

        return f"{month} {day}"

    numeric_date = re.search(
        r"\b(?:by|before|on)?\s*"
        r"(\d{1,2})[/-](\d{1,2})"
        r"(?:[/-](\d{2,4}))?\b",
        text,
        flags=re.I
    )

    if numeric_date:

        day = numeric_date.group(1)
        month = numeric_date.group(2)
        year = numeric_date.group(3)

        if year:
            return f"{day}/{month}/{year}"

        return f"{day}/{month}"

    return "Not specified"


# =========================================================
# PRIORITY
# =========================================================

def detect_priority(sentence):

    text = clean_text(sentence).lower()

    high_words = [
        "urgent",
        "critical",
        "asap",
        "immediately",
        "high priority",
        "important"
    ]

    medium_words = [
        "medium priority",
        "moderate",
        "soon"
    ]

    if any(
        word in text
        for word in high_words
    ):
        return "High"

    if any(
        word in text
        for word in medium_words
    ):
        return "Medium"

    return "Low"


# =========================================================
# TASK FILTERING
# =========================================================

IGNORE_PHRASES = [
    "let's make this project successful",
    "lets make this project successful",
    "let's make this project",
    "lets make this project",
    "let's start working",
    "lets start working",
    "great work",
    "great job",
    "good work",
    "good job",
    "nice work",
    "well done",
    "we'll make sure everyone stays informed",
    "we will make sure everyone stays informed",
    "everyone stays informed",
    "good teamwork depends",
    "teamwork depends",
    "clear communication",
    "communication is",
    "finish them on time",
    "successful project",
    "first, we need to divide the tasks",
    "first we need to divide the tasks",
    "we need to divide the tasks among the team"
]


def is_ignored_sentence(sentence):

    text = clean_text(sentence).lower()

    for phrase in IGNORE_PHRASES:

        if phrase in text:
            return True

    # Questions are discussion, not action items
    if text.endswith("?"):
        return True

    if len(text.split()) <= 4:

        short_ignore = [
            "great work everyone",
            "great work",
            "good job",
            "good teamwork",
            "nice work",
            "well done"
        ]

        if text in short_ignore:
            return True

    return False


def is_real_task(sentence):

    text = clean_text(sentence)

    if not text:
        return False

    if is_ignored_sentence(text):
        return False

    lower = text.lower()

    # Explicit assignment
    if re.search(
        r"\b[A-Za-z][A-Za-z0-9_-]*\s+"
        r"(?:will|shall|can|is going to|has to|needs to|must)\b",
        text,
        re.I
    ):
        return True

    # First person action
    if re.search(
        r"\b(?:I|we|our team)\s+"
        r"(?:will|shall|can|need to|have to|must|"
        r"am going to|are going to)\b",
        text,
        re.I
    ):
        return True

    # Task verbs
    action_verbs = [
        "prepare",
        "complete",
        "finish",
        "create",
        "design",
        "develop",
        "test",
        "check",
        "review",
        "submit",
        "collect",
        "organize",
        "update",
        "fix",
        "build",
        "implement",
        "research",
        "present",
        "record",
        "upload",
        "deploy",
        "write",
        "edit",
        "install",
        "configure"
    ]

    for verb in action_verbs:

        if re.search(
            r"\b" + re.escape(verb) + r"\b",
            lower
        ):
            return True

    # Explicit obligation
    if re.search(
        r"\b(?:need to|needs to|has to|have to|must|"
        r"responsible for|assigned to)\b",
        lower
    ):
        return True

    return False


# =========================================================
# SENTENCE SPLITTING
# =========================================================

def split_sentences(transcript):

    text = clean_text(transcript)

    if not text:
        return []

    # Help Whisper output split into assignment sentences.
    text = re.sub(
        r"\s+(?=(?:I|We|They|The team|[A-Z][a-z]+)\s+"
        r"(?:will|shall|can|must|needs to|has to)\b)",
        ". ",
        text
    )

    parts = re.split(
        r"(?<=[.!?])\s+|[\r\n]+",
        text
    )

    return [
        clean_text(part)
        for part in parts
        if clean_text(part)
    ]


# =========================================================
# TASK EXTRACTION
# =========================================================

def extract_tasks(transcript):

    sentences = split_sentences(
        transcript
    )

    tasks = []
    seen = set()

    for sentence in sentences:

        if not is_real_task(sentence):
            continue

        sentence = sentence.strip(
            " .,!;:"
        )

        owner = detect_owner(
            sentence
        )

        deadline = detect_deadline(
            sentence
        )

        priority = detect_priority(
            sentence
        )

        task_text = normalize_task(
            sentence
        )

        if not task_text:
            continue

        if len(task_text.split()) < 3:
            continue

        duplicate_key = re.sub(
            r"[^a-z0-9]+",
            " ",
            task_text.lower()
        ).strip()

        if duplicate_key in seen:
            continue

        seen.add(duplicate_key)

        tasks.append({
            "task": task_text,
            "owner": owner,
            "deadline": deadline,
            "priority": priority
        })

    return tasks


# =========================================================
# DELETE TASKS FOR ONE MEETING
# =========================================================

def delete_meeting_tasks(meeting_id):

    conn = get_db()

    conn.execute(
        "DELETE FROM tasks WHERE meeting_id = ?",
        (meeting_id,)
    )

    conn.commit()
    conn.close()


# =========================================================
# DUPLICATE CLEANUP
# =========================================================

def cleanup_duplicate_tasks():

    conn = get_db()

    rows = conn.execute("""
        SELECT id, meeting_id, task
        FROM tasks
        ORDER BY id ASC
    """).fetchall()

    seen = set()
    delete_ids = []

    for row in rows:

        task = clean_text(
            row["task"]
        )

        key = re.sub(
            r"[^a-z0-9]+",
            " ",
            task.lower()
        ).strip()

        if not key:

            delete_ids.append(
                row["id"]
            )

            continue

        meeting_key = (
            row["meeting_id"],
            key
        )

        if meeting_key in seen:

            delete_ids.append(
                row["id"]
            )

        else:

            seen.add(
                meeting_key
            )

    if delete_ids:

        conn.executemany(
            "DELETE FROM tasks WHERE id = ?",
            [
                (task_id,)
                for task_id in delete_ids
            ]
        )

    conn.commit()
    conn.close()


# =========================================================
# TRANSCRIPTION
# =========================================================

def transcribe_audio(audio_path):

    model = get_whisper_model()

    print(
        "Transcription started..."
    )

    segments, info = model.transcribe(
        audio_path,
        beam_size=1,
        vad_filter=True
    )

    text_parts = []

    for segment in segments:

        text = segment.text.strip()

        if text:
            text_parts.append(
                text
            )

    transcript = " ".join(
        text_parts
    )

    print(
        "Transcription completed."
    )

    return transcript


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# AUDIO UPLOAD
# =========================================================

@app.route(
    "/upload_audio",
    methods=["POST"]
)
def upload_audio():

    if "audio" not in request.files:

        flash(
            "Please select an audio file."
        )

        return redirect(
            url_for("home")
        )

    file = request.files["audio"]

    if not file or not file.filename:

        flash(
            "No audio file selected."
        )

        return redirect(
            url_for("home")
        )

    if not allowed_file(
        file.filename
    ):

        flash(
            "Unsupported audio format."
        )

        return redirect(
            url_for("home")
        )

    original_name = secure_filename(
        file.filename
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    filename = (
        timestamp
        + "_"
        + original_name
    )

    filepath = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    file.save(filepath)

    print(
        f"Audio saved: {filepath}"
    )

    try:

        transcript = transcribe_audio(
            filepath
        )

    except Exception as e:

        print(
            "Transcription error:",
            repr(e)
        )

        flash(
            "Audio transcription failed."
        )

        return redirect(
            url_for("home")
        )

    summary = generate_summary(
        transcript
    )

    conn = get_db()

    # IMPORTANT:
    # participants is explicitly inserted
    # because existing database has NOT NULL constraint.
    cursor = conn.execute("""
        INSERT INTO meetings
        (
            title,
            transcript,
            summary,
            participants,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        "Audio Meeting",
        transcript,
        summary,
        "",
        datetime.now().isoformat()
    ))

    meeting_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "meeting_page",
            meeting_id=meeting_id
        )
    )


# =========================================================
# NOTES MEETING
# =========================================================

@app.route(
    "/meeting",
    methods=["POST"]
)
def create_meeting():

    transcript = request.form.get(
        "notes",
        ""
    ).strip()

    title = request.form.get(
        "title",
        "Meeting"
    ).strip()

    if not transcript:

        flash(
            "Please enter meeting notes."
        )

        return redirect(
            url_for("home")
        )

    if not title:
        title = "Meeting"

    summary = generate_summary(
        transcript
    )

    conn = get_db()

    # IMPORTANT:
    # participants explicitly supplied.
    cursor = conn.execute("""
        INSERT INTO meetings
        (
            title,
            transcript,
            summary,
            participants,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        title,
        transcript,
        summary,
        "",
        datetime.now().isoformat()
    ))

    meeting_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "meeting_page",
            meeting_id=meeting_id
        )
    )


# =========================================================
# MEETING PAGE
# =========================================================

@app.route(
    "/meeting/<int:meeting_id>"
)
def meeting_page(meeting_id):

    conn = get_db()

    meeting = conn.execute("""
        SELECT *
        FROM meetings
        WHERE id = ?
    """, (
        meeting_id,
    )).fetchone()

    conn.close()

    if not meeting:

        return (
            "Meeting not found",
            404
        )

    return render_template(
        "transcription.html",
        meeting=meeting
    )


# =========================================================
# ANALYZE
# =========================================================

@app.route(
    "/analyze",
    methods=["POST"]
)
def analyze():

    meeting_id = request.form.get(
        "meeting_id"
    )

    if not meeting_id:

        return redirect(
            url_for("home")
        )

    try:

        meeting_id = int(
            meeting_id
        )

    except ValueError:

        return redirect(
            url_for("home")
        )

    conn = get_db()

    meeting = conn.execute("""
        SELECT *
        FROM meetings
        WHERE id = ?
    """, (
        meeting_id,
    )).fetchone()

    conn.close()

    if not meeting:

        return (
            "Meeting not found",
            404
        )

    transcript = (
        meeting["transcript"]
        or ""
    )

    tasks = extract_tasks(
        transcript
    )

    # Delete only this meeting's old tasks.
    delete_meeting_tasks(
        meeting_id
    )

    conn = get_db()

    now = datetime.now().isoformat()

    for item in tasks:

        conn.execute("""
            INSERT INTO tasks
            (
                meeting_id,
                task,
                owner,
                deadline,
                priority,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            meeting_id,
            item["task"],
            item["owner"],
            item["deadline"],
            item["priority"],
            "Pending",
            now
        ))

    summary = generate_summary(
        transcript
    )

    conn.execute("""
        UPDATE meetings
        SET summary = ?
        WHERE id = ?
    """, (
        summary,
        meeting_id
    ))

    conn.commit()
    conn.close()

    print(
        f"Meeting {meeting_id} analyzed."
    )

    print(
        f"Tasks detected: {len(tasks)}"
    )

    return redirect(
        url_for(
            "dashboard",
            meeting_id=meeting_id
        )
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    requested_meeting_id = request.args.get(
        "meeting_id"
    )

    conn = get_db()

    meeting_id = None

    if requested_meeting_id:

        try:

            meeting_id = int(
                requested_meeting_id
            )

        except ValueError:

            meeting_id = None

    # If no meeting ID, use newest meeting.
    if meeting_id is None:

        latest_meeting = conn.execute("""
            SELECT id
            FROM meetings
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if latest_meeting:

            meeting_id = (
                latest_meeting["id"]
            )

    # -----------------------------------------------------
    # IMPORTANT:
    # Only selected/latest meeting tasks.
    # -----------------------------------------------------

    if meeting_id:

        tasks = conn.execute("""
            SELECT *
            FROM tasks
            WHERE meeting_id = ?
            ORDER BY id ASC
        """, (
            meeting_id,
        )).fetchall()

    else:

        tasks = []

    # -----------------------------------------------------
    # Current meeting
    # -----------------------------------------------------

    meeting = None

    if meeting_id:

        meeting = conn.execute("""
            SELECT *
            FROM meetings
            WHERE id = ?
        """, (
            meeting_id,
        )).fetchone()

    # -----------------------------------------------------
    # Counts
    # -----------------------------------------------------

    total_tasks = len(tasks)

    pending_tasks = sum(
        1
        for task in tasks
        if (
            task["status"]
            or "Pending"
        ).lower() == "pending"
    )

    completed_tasks = sum(
        1
        for task in tasks
        if (
            task["status"]
            or ""
        ).lower() == "completed"
    )

    # Do not falsely mark text deadlines as overdue.
    overdue_tasks = 0

    conn.close()

    return render_template(
        "dashboard.html",
        tasks=tasks,
        meeting=meeting,
        total_tasks=total_tasks,
        pending_tasks=pending_tasks,
        completed_tasks=completed_tasks,
        overdue_tasks=overdue_tasks
    )


# =========================================================
# UPDATE OWNER
# =========================================================

@app.route(
    "/update_owner/<int:task_id>",
    methods=["POST"]
)
def update_owner(task_id):

    owner = request.form.get(
        "owner",
        "Unassigned"
    ).strip()

    if not owner:
        owner = "Unassigned"

    conn = get_db()

    conn.execute("""
        UPDATE tasks
        SET owner = ?
        WHERE id = ?
    """, (
        owner,
        task_id
    ))

    conn.commit()
    conn.close()

    return redirect(
        request.referrer
        or url_for("dashboard")
    )


# =========================================================
# COMPLETE TASK
# =========================================================

@app.route(
    "/complete/<int:task_id>",
    methods=["POST"]
)
def complete_task(task_id):

    conn = get_db()

    task = conn.execute("""
        SELECT status
        FROM tasks
        WHERE id = ?
    """, (
        task_id,
    )).fetchone()

    if task:

        current_status = (
            task["status"]
            or "Pending"
        )

        if current_status.lower() != "completed":

            new_status = "Completed"

        else:

            new_status = "Pending"

        conn.execute("""
            UPDATE tasks
            SET status = ?
            WHERE id = ?
        """, (
            new_status,
            task_id
        ))

        conn.commit()

    conn.close()

    return redirect(
        request.referrer
        or url_for("dashboard")
    )


# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def history():

    conn = get_db()

    meetings = conn.execute("""
        SELECT
            m.*,
            COUNT(t.id) AS task_count
        FROM meetings m
        LEFT JOIN tasks t
            ON m.id = t.meeting_id
        GROUP BY m.id
        ORDER BY m.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "history.html",
        meetings=meetings
    )


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/notifications")
def notifications():

    conn = get_db()

    tasks = conn.execute("""
        SELECT *
        FROM tasks
        WHERE status != 'Completed'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "notifications.html",
        tasks=tasks
    )


# =========================================================
# PROBLEMS
# =========================================================

@app.route("/problems")
def problems():

    conn = get_db()

    problems = conn.execute("""
        SELECT *
        FROM problems
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "problems.html",
        problems=problems
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return {
        "status": "ok",
        "service": "Meet2ActionAI"
    }


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(413)
def file_too_large(error):

    return (
        "Uploaded file is too large.",
        413
    )


@app.errorhandler(404)
def page_not_found(error):

    return (
        "Page not found.",
        404
    )


# =========================================================
# STARTUP
# =========================================================

init_db()

cleanup_duplicate_tasks()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    print()
    print("======================================")
    print("      Meet2ActionAI is starting")
    print("======================================")
    print()

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )