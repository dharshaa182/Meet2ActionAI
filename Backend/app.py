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

    # First-person assignment
    if re.search(
        r"\b(i will|i'll|i can|i am going to)\b",
        text_lower
    ):
        return "Self"

    return "Unassigned"


# ============================================================
# DEADLINE DETECTION
# ============================================================

def detect_deadline(text):

    text_lower = text.lower()

    patterns = [
        r"\bby today\b",
        r"\btoday\b",
        r"\bby tomorrow\b",
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
        "critical",
        "emergency"
    ]

    for word in high_words:

        if word in text_lower:
            return "High"

    medium_words = [
        "soon",
        "this week",
        "priority"
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
# SMART TASK EXTRACTION
# ============================================================

def extract_tasks(transcript, meeting_id):

    if not transcript:
        return

    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript.strip()
    )

    # --------------------------------------------------------
    # Real action phrases
    # --------------------------------------------------------

    action_patterns = [

        # Personal commitments
        r"\bi will\b",
        r"\bi'll\b",
        r"\bi can\b",
        r"\bi am going to\b",

        # Team commitments
        r"\bwe will\b",
        r"\bwe'll\b",
        r"\bwe need to\b",
        r"\bwe have to\b",

        # Assignment / responsibility
        r"\bassigned to\b",
        r"\bresponsible for\b",
        r"\bhas to\b",
        r"\bhave to\b",
        r"\bneeds to\b",
        r"\bneed to\b",
        r"\bmust\b",

        # Direct actions
        r"\bprepare\b",
        r"\bcreate\b",
        r"\bdevelop\b",
        r"\bdesign\b",
        r"\bsubmit\b",
        r"\bcomplete\b",
        r"\bfinish\b",
        r"\btest\b",
        r"\breview\b",
        r"\bcheck\b",
        r"\bsend\b",
        r"\bupdate\b",
        r"\borganize\b",
        r"\bcollect\b",
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bfix\b",
        r"\bfinalize\b",
        r"\bpresent\b",
        r"\bprepare\b",
        r"\binstall\b",
        r"\bdeploy\b",
        r"\bdocument\b"
    ]

    # --------------------------------------------------------
    # General / useless statements
    # --------------------------------------------------------

    blocked_patterns = [

        r"^\s*where\b",
        r"^\s*what\b",
        r"^\s*when\b",
        r"^\s*who\b",
        r"^\s*why\b",
        r"^\s*how\b",

        r"\bwhere should\b",
        r"\bwhat should\b",
        r"\bwhen should\b",
        r"\bwhy should\b",
        r"\bhow should\b",

        r"\bi think\b",
        r"\bi believe\b",
        r"\bi feel\b",

        r"\bcommunication will be important\b",
        r"\bwill be important\b",

        r"\bwe should also update\b",
        r"\bwe should share updates\b",
        r"\bshare updates regularly\b",

        r"\bthat gives us enough time\b",
        r"\benough time to check\b",

        r"\bmake this project successful\b",
        r"\bmake this project a success\b",

        r"\bstays informed\b",
        r"\bstay informed\b",

        r"\bwhat should we focus on\b",
        r"\bwhen should we finish\b"
    ]

    # --------------------------------------------------------
    # Words that indicate a question
    # --------------------------------------------------------

    question_words = [
        "where",
        "what",
        "when",
        "who",
        "why",
        "how"
    ]

    conn = get_db()
    cursor = conn.cursor()

    inserted_tasks = set()

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        # Normalize spaces
        sentence = re.sub(
            r"\s+",
            " ",
            sentence
        ).strip()

        # Too short
        if len(sentence.split()) < 4:
            continue

        sentence_lower = sentence.lower()

        # ----------------------------------------------------
        # NEVER accept questions
        # ----------------------------------------------------

        if "?" in sentence:
            continue

        first_word_match = re.match(
            r"^\s*([a-zA-Z]+)",
            sentence_lower
        )

        if first_word_match:

            first_word = first_word_match.group(1)

            if first_word in question_words:
                continue

        # ----------------------------------------------------
        # Block useless/general statements
        # ----------------------------------------------------

        blocked = False

        for pattern in blocked_patterns:

            if re.search(
                pattern,
                sentence_lower
            ):
                blocked = True
                break

        if blocked:
            continue

        # ----------------------------------------------------
        # Find action
        # ----------------------------------------------------

        is_action = False

        for pattern in action_patterns:

            if re.search(
                pattern,
                sentence_lower
            ):
                is_action = True
                break

        if not is_action:
            continue

        # ----------------------------------------------------
        # Reject vague statements
        # ----------------------------------------------------

        vague_phrases = [
            "should be",
            "will be",
            "is important",
            "are important",
            "enough time",
            "stay informed",
            "share updates regularly",
            "communication will be"
        ]

        if any(
            phrase in sentence_lower
            for phrase in vague_phrases
        ):
            continue

        # ----------------------------------------------------
        # Clean task
        # ----------------------------------------------------

        task_text = sentence.strip()

        task_text = task_text.rstrip(
            ".!?"
        )

        if not task_text:
            continue

        # ----------------------------------------------------
        # Prevent duplicate tasks
        # ----------------------------------------------------

        normalized_task = re.sub(
            r"[^a-z0-9\s]",
            "",
            task_text.lower()
        )

        normalized_task = re.sub(
            r"\s+",
            " ",
            normalized_task
        ).strip()

        if not normalized_task:
            continue

        if normalized_task in inserted_tasks:
            continue

        # Check duplicate inside same meeting
        cursor.execute("""
            SELECT id
            FROM tasks
            WHERE meeting_id = ?
            AND LOWER(TRIM(task)) = LOWER(TRIM(?))
            LIMIT 1
        """, (
            meeting_id,
            task_text
        ))

        if cursor.fetchone():
            continue

        inserted_tasks.add(
            normalized_task
        )

        # ----------------------------------------------------
        # Extract metadata
        # ----------------------------------------------------

        owner = detect_owner(
            task_text
        )

        deadline = detect_deadline(
            task_text
        )

        priority = detect_priority(
            task_text
        )

        # ----------------------------------------------------
        # Insert task
        # ----------------------------------------------------

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
            task_text,
            owner,
            deadline,
            priority,
            "Pending"
        ))

    conn.commit()
    conn.close()


# ============================================================
# CLEAN OLD JUNK TASKS
# ============================================================

def cleanup_old_tasks():

    conn = get_db()
    cursor = conn.cursor()

    # Remove obvious questions
    cursor.execute("""
        DELETE FROM tasks
        WHERE
            TRIM(task) LIKE 'Where %'
            OR TRIM(task) LIKE 'What %'
            OR TRIM(task) LIKE 'When %'
            OR TRIM(task) LIKE 'Who %'
            OR TRIM(task) LIKE 'Why %'
            OR TRIM(task) LIKE 'How %'
    """)

    # Remove obvious general statements
    junk_phrases = [
        "communication will be important",
        "we should share updates regularly",
        "we should also update the team about our progress",
        "that gives us enough time to check our work",
        "we'll make sure everyone stays informed",
        "we should share updates regularly",
        "make this project successful"
    ]

    for phrase in junk_phrases:

        cursor.execute("""
            DELETE FROM tasks
            WHERE LOWER(task) LIKE ?
        """, (
            "%" + phrase.lower() + "%",
        ))

    # --------------------------------------------------------
    # Remove exact duplicate tasks within the same meeting
    # Keep newest task.
    # --------------------------------------------------------

    cursor.execute("""
        DELETE FROM tasks
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM tasks
            GROUP BY
                meeting_id,
                LOWER(TRIM(task))
        )
    """)

    conn.commit()
    conn.close()

    print("Old junk/duplicate tasks cleaned.")


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

@app.route(
    "/upload_audio",
    methods=["GET"]
)
def upload_audio_page():

    return render_template(
        "upload_audio.html"
    )


# ============================================================
# UPLOAD AUDIO
# ============================================================

@app.route(
    "/upload_audio",
    methods=["POST"]
)
def upload_audio():

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

        # Create smart action items
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

    if not notes:

        return (
            "Please enter meeting notes.",
            400
        )

    if not title:

        title = "Audio Meeting"

    if not participants:

        detected = detect_participants(
            notes
        )

        participants = (
            ", ".join(detected)
            or "Not detected"
        )

    summary = generate_summary(
        notes
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

    extract_tasks(
        notes,
        meeting_id
    )

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

    # Basic overdue calculation
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
        <a href="/upload_audio">Go Back</a>
        """, 500

    finally:

        if os.path.exists(file_path):

            try:
                os.remove(file_path)

            except Exception:
                pass


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def file_too_large(error):

    return """
    <h2>File Too Large</h2>
    <p>Maximum audio file size is 25 MB.</p>
    <a href="/upload_audio">Upload another file</a>
    """, 413


@app.errorhandler(404)
def page_not_found(error):

    return """
    <h2>Page Not Found</h2>
    <a href="/">Go Home</a>
    """, 404


@app.errorhandler(500)
def internal_error(error):

    return """
    <h2>Internal Server Error</h2>
    <p>Please try again.</p>
    <a href="/">Go Home</a>
    """, 500


# ============================================================
# STARTUP
# ============================================================

init_db()

# Clean old junk tasks when app starts
try:
    cleanup_old_tasks()
except Exception as e:
    print(
        "TASK CLEANUP ERROR:",
        str(e)
    )


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False
    )