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
# ALLOWED AUDIO
# ============================================================

ALLOWED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".webm",
    ".ogg",
    ".mp4",
    ".mpeg"
}


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
# OWNER DETECTION
# ============================================================

def detect_owner(text):

    text_lower = text.lower()

    # Named person gets highest priority
    for person in PEOPLE:

        if re.search(
            r"\b" + re.escape(person.lower()) + r"\b",
            text_lower
        ):
            return person

    # First-person commitment
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
        "medium priority"
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

    return " ".join(
        sentences[:3]
    )


# ============================================================
# TASK TEXT NORMALIZATION
# ============================================================

def normalize_task(text):

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# ============================================================
# TASK EXTRACTION
# ============================================================

def extract_tasks(transcript, meeting_id):

    if not transcript:
        return

    # Split transcript into sentences
    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript.strip()
    )

    conn = get_db()
    cursor = conn.cursor()

    inserted_tasks = set()

    for sentence in sentences:

        sentence = re.sub(
            r"\s+",
            " ",
            sentence.strip()
        )

        if not sentence:
            continue

        # Minimum sentence length
        if len(sentence.split()) < 4:
            continue

        text = sentence.rstrip(".!?").strip()
        lower = text.lower()

        # ====================================================
        # REJECT QUESTIONS
        # ====================================================

        if "?" in sentence:
            continue

        if re.match(
            r"^(where|what|when|who|why|how)\b",
            lower
        ):
            continue

        # ====================================================
        # REJECT NORMAL DISCUSSION
        # ====================================================

        blocked_phrases = [

            # General discussion
            "great work",
            "good teamwork",
            "clear communication",
            "communication will be",
            "will be important",

            # Opinion
            "i think",
            "i believe",
            "i feel",
            "i guess",
            "i suppose",

            # Generic team statements
            "we can work together",
            "work together and finish",
            "let's start working",
            "let us start working",
            "let's get started",
            "let us get started",

            # Planning discussion
            "first, we need to divide",
            "first we need to divide",
            "we should divide the tasks",
            "we should share updates",
            "we should also update",

            # Informational statements
            "stay informed",
            "stays informed",
            "enough time",
            "gives us enough time",
            "make this project successful",
            "make this project a success",

            # Questions accidentally transcribed without ?
            "when should we finish",
            "what should we focus",
            "where should we go",
            "what should we do",
            "how should we",

            # Generic completion statements
            "complete everything",
            "finish everything",
            "finish them on time",
            "finish them by",
            "complete them on time"
        ]

        if any(
            phrase in lower
            for phrase in blocked_phrases
        ):
            continue

        # ====================================================
        # REJECT SENTENCES STARTING WITH GENERAL WORDS
        # ====================================================

        if re.match(
            r"^(yes|no|okay|ok|great|good|sure|right|actually|maybe|probably)\b",
            lower
        ):
            continue

        # ====================================================
        # EXPLICIT ACTION PATTERNS
        # ====================================================

        valid_patterns = [

            # Personal commitment
            r"\bi will\b",
            r"\bi'll\b",
            r"\bi can\b",
            r"\bi am going to\b",

            # Team commitment
            r"\bwe will\b",
            r"\bwe'll\b",
            r"\bwe have to\b",
            r"\bwe need to\b",

            # Assignment
            r"\bassigned to\b",
            r"\bresponsible for\b",
            r"\bhas to\b",
            r"\bhave to\b",
            r"\bneeds to\b",
            r"\bneed to\b",
            r"\bmust\b",

            # Direct action
            r"\bprepare\b",
            r"\bcreate\b",
            r"\bdevelop\b",
            r"\bdesign\b",
            r"\bsubmit\b",
            r"\btest\b",
            r"\breview\b",
            r"\bsend\b",
            r"\borganize\b",
            r"\bcollect\b",
            r"\bimplement\b",
            r"\bbuild\b",
            r"\bfix\b",
            r"\bfinalize\b",
            r"\bpresent\b",
            r"\binstall\b",
            r"\bdeploy\b",
            r"\bdocument\b"
        ]

        if not any(
            re.search(pattern, lower)
            for pattern in valid_patterns
        ):
            continue

        # ====================================================
        # REJECT VAGUE "SHOULD/WILL BE"
        # ====================================================

        if re.search(
            r"\b(should|would|could|will)\s+be\b",
            lower
        ):
            continue

        if re.search(
            r"\b(is|are)\s+important\b",
            lower
        ):
            continue

        # ====================================================
        # CLEAN COMMITMENT PREFIX
        # ====================================================

        task_text = text

        prefixes = [
            r"^i will\s+",
            r"^i'll\s+",
            r"^i can\s+",
            r"^i am going to\s+",
            r"^we will\s+",
            r"^we'll\s+"
        ]

        for prefix in prefixes:

            task_text = re.sub(
                prefix,
                "",
                task_text,
                flags=re.IGNORECASE
            ).strip()

        # ====================================================
        # DO NOT TURN GENERIC "LET'S" INTO TASK
        # ====================================================

        if lower.startswith("let's "):

            action = lower[7:].strip()

            if action in [
                "start working",
                "get started",
                "work together",
                "complete everything by friday afternoon"
            ]:
                continue

            # Only allow clearly specific actions
            if not re.match(
                r"^(prepare|create|develop|design|submit|test|review|send|organize|collect|implement|build|fix|finalize|present|install|deploy|document)\b",
                action
            ):
                continue

            task_text = re.sub(
                r"^let's\s+",
                "",
                task_text,
                flags=re.IGNORECASE
            ).strip()

        # ====================================================
        # CLEAN TASK
        # ====================================================

        task_text = task_text.rstrip(
            ".!?"
        ).strip()

        if not task_text:
            continue

        if len(task_text.split()) < 3:
            continue

        # ====================================================
        # REJECT GENERIC TASK TEXT
        # ====================================================

        generic_tasks = [
            "complete everything",
            "finish everything",
            "start working",
            "get started",
            "work together",
            "finish them on time",
            "finish them",
            "complete them"
        ]

        if normalize_task(task_text) in generic_tasks:
            continue

        # ====================================================
        # DUPLICATE PROTECTION
        # ====================================================

        normalized = normalize_task(
            task_text
        )

        if not normalized:
            continue

        if normalized in inserted_tasks:
            continue

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

        # ====================================================
        # METADATA
        # ====================================================

        owner = detect_owner(text)

        deadline = detect_deadline(text)

        priority = detect_priority(text)

        # ====================================================
        # INSERT
        # ====================================================

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

        inserted_tasks.add(
            normalized
        )

    conn.commit()
    conn.close()

    print(
        f"Task extraction completed for meeting {meeting_id}."
    )


# ============================================================
# CLEAN OLD JUNK + DUPLICATES
# ============================================================

def cleanup_old_tasks():

    conn = get_db()
    cursor = conn.cursor()

    # ========================================================
    # REMOVE QUESTIONS
    # ========================================================

    cursor.execute("""
        DELETE FROM tasks
        WHERE
            LOWER(TRIM(task)) LIKE 'where %'
            OR LOWER(TRIM(task)) LIKE 'what %'
            OR LOWER(TRIM(task)) LIKE 'when %'
            OR LOWER(TRIM(task)) LIKE 'who %'
            OR LOWER(TRIM(task)) LIKE 'why %'
            OR LOWER(TRIM(task)) LIKE 'how %'
    """)

    # ========================================================
    # REMOVE KNOWN JUNK
    # ========================================================

    junk_phrases = [

        "great work",
        "good teamwork",
        "clear communication",
        "communication will be important",
        "will be important",

        "i think",
        "i believe",
        "i feel",

        "let's start working",
        "let us start working",

        "we can work together",
        "work together and finish",

        "first, we need to divide",
        "first we need to divide",

        "we should share updates",
        "we should also update",

        "stay informed",
        "stays informed",

        "enough time",
        "gives us enough time",

        "make this project successful",
        "make this project a success",

        "complete everything",
        "finish everything",
        "finish them on time",

        "when should we finish",
        "what should we focus",
        "where should we go",
        "what should we do",
        "how should we"
    ]

    for phrase in junk_phrases:

        cursor.execute("""
            DELETE FROM tasks
            WHERE LOWER(TRIM(task)) LIKE ?
        """, (
            "%" + phrase.lower() + "%",
        ))

    # ========================================================
    # REMOVE GENERIC SENTENCES
    # ========================================================

    cursor.execute("""
        DELETE FROM tasks
        WHERE LOWER(TRIM(task)) IN (
            'start working',
            'get started',
            'work together',
            'finish them',
            'complete them',
            'finish them on time',
            'complete everything',
            'finish everything'
        )
    """)

    # ========================================================
    # GLOBAL EXACT DUPLICATE CLEANUP
    # ========================================================
    # Keeps newest copy of exactly same task.
    # ========================================================

    cursor.execute("""
        DELETE FROM tasks
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM tasks
            GROUP BY LOWER(TRIM(task))
        )
    """)

    conn.commit()
    conn.close()

    print("Old junk and duplicate tasks cleaned.")


# ============================================================
# PARTICIPANTS
# ============================================================

def detect_participants(transcript):

    participants = []

    if not transcript:
        return participants

    transcript_lower = transcript.lower()

    for person in PEOPLE:

        if re.search(
            r"\b" + re.escape(person.lower()) + r"\b",
            transcript_lower
        ):
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

    if extension not in ALLOWED_EXTENSIONS:

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
# MANUAL MEETING
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
        "Meeting"
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

        title = "Meeting"

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

    # Future improvement:
    # Calculate real date-based overdue tasks.
    overdue_tasks = conn.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status = 'Overdue'
    """).fetchone()[0]

    tasks = conn.execute("""
        SELECT
            id,
            meeting_id,
            task,
            owner,
            deadline,
            priority,
            status
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

    if extension not in ALLOWED_EXTENSIONS:

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