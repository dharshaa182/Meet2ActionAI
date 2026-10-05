from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
import re
import os
import uuid
from datetime import datetime
from faster_whisper import WhisperModel

# ============================================================
# APP
# ============================================================

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================

app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

UPLOAD_FOLDER = "uploads"
DB_NAME = "meet2action.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "Meet2Action AI"
    })


# ============================================================
# WHISPER MODEL
# ============================================================

whisper_model = None


def get_whisper_model():
    global whisper_model

    if whisper_model is None:
        print("Loading Whisper tiny model...")

        whisper_model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1
        )

        print("Whisper model loaded.")

    return whisper_model


def transcribe_audio(file_path):

    model = get_whisper_model()

    print("Starting transcription...")

    segments, info = model.transcribe(
        file_path,
        beam_size=1,
        best_of=1,
        temperature=0,
        vad_filter=True,
        condition_on_previous_text=False
    )

    transcript_parts = []

    for segment in segments:

        text = segment.text.strip()

        if text:
            transcript_parts.append(text)

    transcript = " ".join(
        transcript_parts
    ).strip()

    print("Transcription completed.")

    return transcript


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(DB_NAME)

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            participants TEXT,
            transcript TEXT,
            summary TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            task TEXT,
            owner TEXT,
            deadline TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            problem TEXT,
            status TEXT DEFAULT 'Open'
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# PEOPLE
# ============================================================

PEOPLE = [
    "Dharshan",
    "Arun",
    "Kumar",
    "Mubeen",
    "Bala",
    "Pugazhendhi",
    "Naveen"
]


# ============================================================
# OWNER DETECTION
# ============================================================

def detect_owner(text):

    text_lower = text.lower()

    for person in PEOPLE:

        if person.lower() in text_lower:
            return person

    return "Unassigned"


# ============================================================
# DEADLINE DETECTION
# ============================================================

def detect_deadline(text):

    text_lower = text.lower()

    patterns = [
        r"\btoday\b",
        r"\btomorrow\b",
        r"\btonight\b",
        r"\bthis week\b",
        r"\bnext week\b",
        r"\bby monday\b",
        r"\bby tuesday\b",
        r"\bby wednesday\b",
        r"\bby thursday\b",
        r"\bby friday\b",
        r"\bby saturday\b",
        r"\bby sunday\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text_lower
        )

        if match:
            return match.group(0).title()

    return "No deadline"


# ============================================================
# PRIORITY DETECTION
# ============================================================

def detect_priority(text):

    text_lower = text.lower()

    high_words = [
        "urgent",
        "high priority",
        "important",
        "asap",
        "immediately",
        "critical"
    ]

    for word in high_words:

        if word in text_lower:
            return "High"

    medium_words = [
        "soon",
        "this week"
    ]

    for word in medium_words:

        if word in text_lower:
            return "Medium"

    return "Normal"


# ============================================================
# SUMMARY
# ============================================================

def generate_summary(transcript):

    if not transcript:
        return "No meeting summary available."

    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript.strip()
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    if not sentences:
        return "No meeting summary available."

    if len(sentences) <= 3:
        return " ".join(sentences)

    return " ".join(sentences[:3])


# ============================================================
# TASK EXTRACTION
# ============================================================

def extract_tasks(transcript, meeting_id):

    if not transcript:
        return

    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript.strip()
    )

    action_words = [
        "will",
        "should",
        "need to",
        "needs to",
        "must",
        "complete",
        "prepare",
        "finish",
        "submit",
        "create",
        "develop",
        "design",
        "test",
        "check",
        "send",
        "update",
        "review",
        "handle",
        "work on",
        "do"
    ]

    conn = get_db()
    cursor = conn.cursor()

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        sentence_lower = sentence.lower()

        is_action = any(
            word in sentence_lower
            for word in action_words
        )

        if not is_action:
            continue

        owner = detect_owner(sentence)

        deadline = detect_deadline(sentence)

        priority = detect_priority(sentence)

        cursor.execute("""
            INSERT INTO tasks
            (
                meeting_id,
                task,
                owner,
                deadline,
                priority,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            meeting_id,
            sentence,
            owner,
            deadline,
            priority,
            "Pending"
        ))

    conn.commit()
    conn.close()


# ============================================================
# PARTICIPANTS
# ============================================================

def detect_participants(transcript):

    participants = []

    if not transcript:
        return participants

    transcript_lower = transcript.lower()

    for person in PEOPLE:

        if person.lower() in transcript_lower:
            participants.append(person)

    return participants


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# UPLOAD AUDIO PAGE
# ============================================================

@app.route("/upload_audio", methods=["GET"])
def upload_audio_page():

    return render_template(
        "upload_audio.html"
    )


# ============================================================
# UPLOAD AUDIO
# ============================================================

@app.route("/upload_audio", methods=["POST"])
def upload_audio():

    file = request.files.get("audio")

    if not file or file.filename == "":
        return "No audio file selected.", 400

    extension = os.path.splitext(
        file.filename
    )[1].lower()

    allowed_extensions = [
        ".mp3",
        ".wav",
        ".m4a",
        ".webm",
        ".ogg",
        ".mp4",
        ".mpeg"
    ]

    if extension not in allowed_extensions:
        return "Unsupported audio format.", 400

    filename = (
        uuid.uuid4().hex +
        extension
    )

    file_path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    try:

        print("Saving uploaded audio...")

        file.save(file_path)

        print("Audio saved.")

        print("Starting transcription...")

        transcript = transcribe_audio(
            file_path
        )

        if not transcript:
            transcript = (
                "No speech detected in this audio."
            )

        participants = detect_participants(
            transcript
        )

        participant_text = ", ".join(
            participants
        )

        if not participant_text:
            participant_text = "Not detected"

        summary = generate_summary(
            transcript
        )

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO meetings
            (
                title,
                participants,
                transcript,
                summary,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Audio Meeting",
            participant_text,
            transcript,
            summary,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ))

        meeting_id = cursor.lastrowid

        conn.commit()

        conn.close()

        extract_tasks(
            transcript,
            meeting_id
        )

        return redirect(
            f"/meeting/{meeting_id}"
        )

    except Exception as e:

        print(
            "UPLOAD ERROR:",
            str(e)
        )

        return f"""
        <h2>Audio processing failed</h2>
        <p>{str(e)}</p>
        <a href="/upload_audio">Try Again</a>
        """, 500

    finally:

        if os.path.exists(file_path):

            try:
                os.remove(file_path)

            except Exception:
                pass


# ============================================================
# MANUAL MEETING / ANALYZE
# ============================================================

@app.route(
    "/meeting",
    methods=["GET", "POST"]
)
def meeting():

    if request.method == "GET":

        return render_template(
            "meeting.html"
        )

    # -----------------------------
    # GET FORM DATA
    # -----------------------------

    notes = request.form.get(
        "notes",
        ""
    ).strip()

    title = request.form.get(
        "title",
        "Audio Meeting"
    ).strip()

    participants = request.form.get(
        "participants",
        ""
    ).strip()

    # -----------------------------
    # VALIDATION
    # -----------------------------

    if not notes:

        return (
            "Please enter meeting notes.",
            400
        )

    if not title:

        title = "Audio Meeting"

    # -----------------------------
    # PARTICIPANTS
    # -----------------------------

    if not participants:

        detected = detect_participants(
            notes
        )

        participants = (
            ", ".join(detected)
            or "Not detected"
        )

    # -----------------------------
    # SUMMARY
    # -----------------------------

    summary = generate_summary(
        notes
    )

    # -----------------------------
    # SAVE MEETING
    # -----------------------------

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO meetings
        (
            title,
            participants,
            transcript,
            summary,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        title,
        participants,
        notes,
        summary,
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    ))

    meeting_id = cursor.lastrowid

    conn.commit()

    conn.close()

    # -----------------------------
    # EXTRACT TASKS
    # -----------------------------

    extract_tasks(
        notes,
        meeting_id
    )

    # -----------------------------
    # IMPORTANT FIX
    # -----------------------------
    # After Analyze Meeting,
    # go directly to Dashboard.
    # This prevents the same
    # transcription page from
    # appearing again.

    return redirect(
        "/dashboard"
    )


# ============================================================
# MEETING DETAILS
# ============================================================

@app.route(
    "/meeting/<int:meeting_id>"
)
def meeting_details(meeting_id):

    conn = get_db()

    meeting_data = conn.execute("""
        SELECT *
        FROM meetings
        WHERE id = ?
    """, (
        meeting_id,
    )).fetchone()

    tasks = conn.execute("""
        SELECT *
        FROM tasks
        WHERE meeting_id = ?
        ORDER BY id DESC
    """, (
        meeting_id,
    )).fetchall()

    conn.close()

    if not meeting_data:

        return (
            "Meeting not found.",
            404
        )

    return render_template(
        "transcription.html",
        meeting=meeting_data,
        tasks=tasks
    )


# ============================================================
# UPDATE OWNER
# ============================================================

@app.route(
    "/update_owner/<int:task_id>",
    methods=["POST"]
)
def update_owner(task_id):

    owner = request.form.get(
        "owner",
        "Unassigned"
    )

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
        or "/dashboard"
    )


# ============================================================
# HISTORY
# ============================================================

@app.route("/history")
def history():

    conn = get_db()

    meetings = conn.execute("""
        SELECT *
        FROM meetings
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "history.html",
        meetings=meetings
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    conn = get_db()

    total_tasks = conn.execute("""
        SELECT COUNT(*)
        FROM tasks
    """).fetchone()[0]

    pending_tasks = conn.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status = 'Pending'
    """).fetchone()[0]

    completed_tasks = conn.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status = 'Completed'
    """).fetchone()[0]

    overdue_tasks = 0

    tasks = conn.execute("""
        SELECT *
        FROM tasks
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_tasks=total_tasks,
        pending_tasks=pending_tasks,
        completed_tasks=completed_tasks,
        overdue_tasks=overdue_tasks,
        tasks=tasks
    )


# ============================================================
# COMPLETE TASK
# ============================================================

@app.route(
    "/complete/<int:task_id>"
)
def complete_task(task_id):

    conn = get_db()

    conn.execute("""
        UPDATE tasks
        SET status = 'Completed'
        WHERE id = ?
    """, (
        task_id,
    ))

    conn.commit()

    conn.close()

    return redirect(
        request.referrer
        or "/dashboard"
    )


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route("/notifications")
def notifications():

    conn = get_db()

    tasks = conn.execute("""
        SELECT *
        FROM tasks
        WHERE status = 'Pending'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "notifications.html",
        tasks=tasks
    )


# ============================================================
# PROBLEMS
# ============================================================

@app.route("/problems")
def problems():

    conn = get_db()

    problems_data = conn.execute("""
        SELECT *
        FROM problems
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "problems.html",
        problems=problems_data
    )


# ============================================================
# ANALYZE AUDIO
# ============================================================

@app.route(
    "/analyze",
    methods=["POST"]
)
def analyze():

    file = request.files.get(
        "audio"
    )

    if not file or file.filename == "":
        return (
            "No audio file selected.",
            400
        )

    extension = os.path.splitext(
        file.filename
    )[1].lower()

    allowed_extensions = [
        ".mp3",
        ".wav",
        ".m4a",
        ".webm",
        ".ogg",
        ".mp4",
        ".mpeg"
    ]

    if extension not in allowed_extensions:
        return (
            "Unsupported audio format.",
            400
        )

    filename = (
        uuid.uuid4().hex +
        extension
    )

    file_path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    try:

        print(
            "Saving audio for analysis..."
        )

        file.save(file_path)

        print(
            "Starting analysis..."
        )

        transcript = transcribe_audio(
            file_path
        )

        if not transcript:

            transcript = (
                "No speech detected."
            )

        summary = generate_summary(
            transcript
        )

        participants = detect_participants(
            transcript
        )

        participant_text = (
            ", ".join(participants)
            or "Not detected"
        )

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO meetings
            (
                title,
                participants,
                transcript,
                summary,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Analyzed Meeting",
            participant_text,
            transcript,
            summary,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ))

        meeting_id = cursor.lastrowid

        conn.commit()

        conn.close()

        extract_tasks(
            transcript,
            meeting_id
        )

        return redirect(
            "/dashboard"
        )

    except Exception as e:

        print(
            "ANALYZE ERROR:",
            str(e)
        )

        return f"""
        <h2>Analysis failed</h2>
        <p>{str(e)}</p>
        <a href="/upload_audio">
        Go Back
        </a>
        """, 500

    finally:

        if os.path.exists(file_path):

            try:
                os.remove(file_path)

            except Exception:
                pass


# ============================================================
# REPORT
# ============================================================

@app.route("/report")
def report():

    conn = get_db()

    meetings = conn.execute("""
        SELECT *
        FROM meetings
        ORDER BY id DESC
    """).fetchall()

    tasks = conn.execute("""
        SELECT *
        FROM tasks
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "report.html",
        meetings=meetings,
        tasks=tasks
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def file_too_large(error):

    return """
    <h2>File too large</h2>
    <p>
    Please upload an audio file
    smaller than 25 MB.
    </p>
    <a href="/upload_audio">
    Go Back
    </a>
    """, 413


@app.errorhandler(500)
def internal_error(error):

    return """
    <h2>Something went wrong</h2>
    <p>Please try again.</p>
    <a href="/">
    Go Home
    </a>
    """, 500


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5001
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )