from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
import re
import os
from datetime import datetime
from faster_whisper import WhisperModel

app = Flask(__name__)

# =========================================================
# PATHS / SETTINGS
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_NAME = os.path.join(BASE_DIR, "meet2action.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "mp4",
    "webm",
    "ogg",
    "mpeg"
}


# =========================================================
# WHISPER MODEL
# =========================================================

model = None


def get_whisper_model():
    """
    Load Whisper only when transcription is required.
    This makes Flask startup faster and safer for Render.
    """

    global model

    if model is None:

        print("Loading Whisper model...")

        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1
        )

        print("Whisper model loaded successfully.")

    return model


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(DB_NAME)

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    # -----------------------------------------------------
    # Meetings
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            participants TEXT NOT NULL DEFAULT 'Not specified',
            transcript TEXT,
            summary TEXT,
            created_at TEXT
        )
        """
    )

    # -----------------------------------------------------
    # Upgrade old database
    # -----------------------------------------------------

    columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(meetings)"
        ).fetchall()
    ]

    if "participants" not in columns:

        conn.execute(
            """
            ALTER TABLE meetings
            ADD COLUMN participants TEXT NOT NULL
            DEFAULT 'Not specified'
            """
        )

    # -----------------------------------------------------
    # Tasks
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            task TEXT,
            owner TEXT,
            deadline TEXT,
            priority TEXT,
            status TEXT DEFAULT 'Pending'
        )
        """
    )

    # -----------------------------------------------------
    # Problems
    # -----------------------------------------------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            problem TEXT,
            created_at TEXT
        )
        """
    )

    conn.commit()

    conn.close()


# =========================================================
# FILE HELPERS
# =========================================================

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

def generate_summary(text):

    if not text:

        return "No summary available."

    clean = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    if len(clean) <= 250:

        return clean

    sentences = re.split(
        r"(?<=[.!?])\s+",
        clean
    )

    summary = " ".join(
        sentences[:3]
    ).strip()

    if not summary:

        summary = clean[:250]

    return summary[:500]


# =========================================================
# OWNER DETECTION
# =========================================================

def detect_owner(sentence):

    text = sentence.strip()

    # -----------------------------------------------------
    # First person
    # -----------------------------------------------------

    if re.search(
        r"\b(I|I'll|I will|I can|I am going to|I'm going to)\b",
        text,
        re.IGNORECASE
    ):

        return "Self"

    # -----------------------------------------------------
    # Team
    # -----------------------------------------------------

    if re.search(
        r"^(we|we'll|we will|we can|the team)\b",
        text,
        re.IGNORECASE
    ):

        return "Team"

    # -----------------------------------------------------
    # Name + will / shall / can
    # -----------------------------------------------------

    match = re.search(
        r"\b([A-Za-z][A-Za-z]+)\s+(?:will|shall|can)\b",
        text,
        re.IGNORECASE
    )

    if match:

        name = match.group(1)

        if name.lower() not in {
            "i",
            "we",
            "the"
        }:

            return name.title()

    # -----------------------------------------------------
    # Explicit assignment
    # -----------------------------------------------------

    match = re.search(
        r"\b(?:assigned to|assign to|responsible for|handled by|owner is)\s+([A-Za-z][A-Za-z]+)",
        text,
        re.IGNORECASE
    )

    if match:

        return match.group(1).title()

    # -----------------------------------------------------
    # Known team members
    # -----------------------------------------------------

    names = [
        "Dharshan",
        "Mubeen",
        "Bala",
        "Pugazhendhi",
        "Naveen",
        "Arun",
        "Kumar",
        "Priya",
        "Kamali"
    ]

    for name in names:

        if re.search(
            rf"\b{name}\b",
            text,
            re.IGNORECASE
        ):

            return name.title()

    return "Unassigned"


# =========================================================
# DEADLINE DETECTION
# =========================================================

def detect_deadline(sentence):

    text = sentence.lower().strip()

    # -----------------------------------------------------
    # Relative deadlines
    # -----------------------------------------------------

    if re.search(r"\btoday\b", text):

        return "Today"

    if re.search(r"\btomorrow\b", text):

        return "Tomorrow"

    if re.search(r"\btonight\b", text):

        return "Tonight"

    if re.search(r"\bthis week\b", text):

        return "This Week"

    if re.search(r"\bnext week\b", text):

        return "Next Week"

    # -----------------------------------------------------
    # Weekdays
    # -----------------------------------------------------

    weekdays = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday"
    ]

    for day in weekdays:

        # by Friday
        if re.search(
            rf"\b(?:by|before|on)\s+{day}\b",
            text
        ):

            return day.title()

        # Friday
        if re.search(
            rf"\b{day}\b",
            text
        ):

            return day.title()

    # -----------------------------------------------------
    # Months
    # -----------------------------------------------------

    months = {
        "january": "January",
        "february": "February",
        "march": "March",
        "april": "April",
        "may": "May",
        "june": "June",
        "july": "July",
        "august": "August",
        "september": "September",
        "october": "October",
        "november": "November",
        "december": "December"
    }

    for month_key, month_name in months.items():

        # October 10
        match = re.search(
            rf"\b{month_key}\s+(\d{{1,2}})\b",
            text
        )

        if match:

            return f"{month_name} {match.group(1)}"

        # 10 October
        match = re.search(
            rf"\b(\d{{1,2}})\s+{month_key}\b",
            text
        )

        if match:

            return f"{month_name} {match.group(1)}"

    # -----------------------------------------------------
    # Numeric dates
    # -----------------------------------------------------

    match = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",
        text
    )

    if match:

        day = match.group(1)
        month = match.group(2)
        year = match.group(3)

        if year:

            return f"{day}/{month}/{year}"

        return f"{day}/{month}"

    return "Not specified"


# =========================================================
# PRIORITY DETECTION
# =========================================================

def detect_priority(sentence):

    text = sentence.lower()

    high_words = [
        "urgent",
        "important",
        "critical",
        "asap",
        "immediately",
        "high priority"
    ]

    medium_words = [
        "medium priority",
        "moderate",
        "soon"
    ]

    for word in high_words:

        if word in text:

            return "High"

    for word in medium_words:

        if word in text:

            return "Medium"

    return "Low"


# =========================================================
# TASK NORMALIZATION
# =========================================================

def normalize_task(sentence):

    task = sentence.strip()

    # -----------------------------------------------------
    # First person
    # -----------------------------------------------------

    task = re.sub(
        r"^(I'll|I will|I can|I’m going to|I'm going to)\s+",
        "",
        task,
        flags=re.IGNORECASE
    )

    # -----------------------------------------------------
    # Team
    # -----------------------------------------------------

    task = re.sub(
        r"^(we will|we can|we should|the team will)\s+",
        "",
        task,
        flags=re.IGNORECASE
    )

    # -----------------------------------------------------
    # Person + will/can/shall
    # -----------------------------------------------------

    task = re.sub(
        r"^[A-Za-z][A-Za-z]+\s+(will|can|shall)\s+",
        "",
        task,
        flags=re.IGNORECASE
    )

    # -----------------------------------------------------
    # Need / must
    # -----------------------------------------------------

    task = re.sub(
        r"^(need to|needs to|has to|have to|must)\s+",
        "",
        task,
        flags=re.IGNORECASE
    )

    task = task.strip()

    if task:

        task = (
            task[0].upper()
            + task[1:]
        )

    return task


# =========================================================
# TASK EXTRACTION
# =========================================================

def extract_tasks(transcript):

    if not transcript:

        return []

    sentences = re.split(
        r"(?<=[.!?])\s+|\n+",
        transcript
    )

    tasks = []

    seen = set()

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:

            continue

        clean = re.sub(
            r"\s+",
            " ",
            sentence
        ).strip()

        lower = clean.lower()

        # -------------------------------------------------
        # Ignore questions
        # -------------------------------------------------

        if "?" in clean:

            continue

        if re.match(
            r"^(what|when|where|who|why|how)\b",
            lower
        ):

            continue

        # -------------------------------------------------
        # Ignore motivational / general statements
        # -------------------------------------------------

        ignore_phrases = [

            "great work",
            "good work",
            "great job",
            "good job",

            "good teamwork",
            "teamwork depends",

            "let's make this project successful",
            "let's make this project",

            "let's start working",

            "we'll make sure",
            "we will make sure",

            "everyone stays informed",
            "stays informed",

            "clear communication",
            "communication is",

            "work together",
            "finish them on time",

            "successful project",
            "nice work",
            "well done"
        ]

        if any(
            phrase in lower
            for phrase in ignore_phrases
        ):

            continue

        # -------------------------------------------------
        # Action keywords
        # -------------------------------------------------

        action_patterns = [

            r"\bwill\b",
            r"\bshall\b",
            r"\bneed to\b",
            r"\bneeds to\b",
            r"\bhas to\b",
            r"\bhave to\b",
            r"\bmust\b",

            r"\bassigned to\b",
            r"\bresponsible for\b",

            r"\bprepare\b",
            r"\bcomplete\b",
            r"\bfinish\b",
            r"\bcreate\b",
            r"\bdesign\b",
            r"\bdevelop\b",
            r"\btest\b",
            r"\bcheck\b",
            r"\breview\b",
            r"\bsubmit\b",
            r"\bcollect\b",
            r"\borganize\b",
            r"\bupdate\b",
            r"\bfix\b",
            r"\bbuild\b",
            r"\bimplement\b",
            r"\bresearch\b",
            r"\bpresent\b",
            r"\brecord\b",
            r"\bupload\b",
            r"\bdeploy\b"
        ]

        is_action = any(
            re.search(
                pattern,
                lower
            )
            for pattern in action_patterns
        )

        if not is_action:

            continue

        # -------------------------------------------------
        # Reject vague discussion
        # -------------------------------------------------

        vague_patterns = [

            "should be",
            "will be important",
            "communication will",

            "we should share",
            "we should also update",

            "that gives us",

            "i think",
            "maybe we",
            "perhaps we",

            "we can discuss",
            "we can work together"
        ]

        if any(
            phrase in lower
            for phrase in vague_patterns
        ):

            continue

        # -------------------------------------------------
        # Normalize
        # -------------------------------------------------

        task = normalize_task(
            clean
        )

        if not task:

            continue

        # -------------------------------------------------
        # Remove punctuation
        # -------------------------------------------------

        task = task.rstrip(
            ".,;:!? "
        )

        # -------------------------------------------------
        # Minimum useful length
        # -------------------------------------------------

        if len(task.split()) < 3:

            continue

        # -------------------------------------------------
        # Deduplicate
        # -------------------------------------------------

        key = re.sub(
            r"[^a-z0-9]+",
            " ",
            task.lower()
        ).strip()

        if key in seen:

            continue

        seen.add(key)

        # -------------------------------------------------
        # Metadata
        # -------------------------------------------------

        owner = detect_owner(
            clean
        )

        deadline = detect_deadline(
            clean
        )

        priority = detect_priority(
            clean
        )

        tasks.append({

            "task": task,

            "owner": owner,

            "deadline": deadline,

            "priority": priority

        })

    return tasks


# =========================================================
# OLD TASK CLEANUP
# =========================================================

def cleanup_old_tasks():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT id, task
        FROM tasks
        ORDER BY id
        """
    ).fetchall()

    seen = set()

    for row in rows:

        task = row["task"] or ""

        key = re.sub(
            r"[^a-z0-9]+",
            " ",
            task.lower()
        ).strip()

        if key in seen:

            conn.execute(
                "DELETE FROM tasks WHERE id = ?",
                (row["id"],)
            )

        else:

            seen.add(key)

    conn.commit()

    conn.close()


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    conn = get_db()

    meetings = conn.execute(
        """
        SELECT *
        FROM meetings
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "index.html",
        meetings=meetings
    )


# =========================================================
# UPLOAD AUDIO
# =========================================================

@app.route(
    "/upload_audio",
    methods=["POST"]
)
def upload_audio():

    if "audio" not in request.files:

        return (
            "No audio file selected.",
            400
        )

    file = request.files["audio"]

    if file.filename == "":

        return (
            "No audio file selected.",
            400
        )

    if not allowed_file(
        file.filename
    ):

        return (
            "Unsupported file type.",
            400
        )

    # -----------------------------------------------------
    # Safe filename
    # -----------------------------------------------------

    safe_filename = re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        file.filename
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    safe_filename = (
        timestamp
        + "_"
        + safe_filename
    )

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        safe_filename
    )

    # -----------------------------------------------------
    # Save audio
    # -----------------------------------------------------

    try:

        file.save(
            filepath
        )

        print(
            f"Audio saved: {filepath}"
        )

    except Exception as e:

        print(
            "File save error:",
            e
        )

        return (
            "Unable to save audio file.",
            500
        )

    # -----------------------------------------------------
    # Transcription
    # -----------------------------------------------------

    try:

        print(
            "Transcription started..."
        )

        whisper_model = get_whisper_model()

        segments, info = whisper_model.transcribe(
            filepath,
            beam_size=1,
            vad_filter=True
        )

        transcript_parts = []

        for segment in segments:

            text = segment.text.strip()

            if text:

                transcript_parts.append(
                    text
                )

        transcript = " ".join(
            transcript_parts
        ).strip()

        print(
            "Transcription completed."
        )

        if not transcript:

            transcript = (
                "No speech was detected "
                "in the uploaded audio."
            )

    except Exception as e:

        print(
            "Transcription error:",
            e
        )

        return (
            f"Transcription error: {str(e)}",
            500
        )

    finally:

        try:

            if os.path.exists(
                filepath
            ):

                os.remove(
                    filepath
                )

        except Exception as e:

            print(
                "Temporary file cleanup error:",
                e
            )

    # -----------------------------------------------------
    # Save meeting
    # -----------------------------------------------------

    try:

        conn = get_db()

        cursor = conn.execute(
            """
            INSERT INTO meetings
            (
                title,
                participants,
                transcript,
                summary,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "Meeting",
                "Not specified",
                transcript,
                generate_summary(
                    transcript
                ),
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        )

        meeting_id = cursor.lastrowid

        conn.commit()

        conn.close()

    except Exception as e:

        print(
            "Database error:",
            e
        )

        return (
            "Unable to save meeting.",
            500
        )

    # -----------------------------------------------------
    # Open meeting page
    # -----------------------------------------------------

    return redirect(
        f"/meeting/{meeting_id}"
    )


# =========================================================
# MEETING NOTES
# =========================================================

@app.route(
    "/meeting",
    methods=["GET", "POST"]
)
def meeting():

    if request.method == "GET":

        return redirect("/")

    notes = request.form.get(
        "notes",
        ""
    ).strip()

    if not notes:

        return (
            "Meeting notes cannot be empty.",
            400
        )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO meetings
        (
            title,
            participants,
            transcript,
            summary,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "Meeting Notes",
            "Not specified",
            notes,
            generate_summary(
                notes
            ),
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )

    meeting_id = cursor.lastrowid

    conn.commit()

    conn.close()

    return redirect(
        f"/meeting/{meeting_id}"
    )


# =========================================================
# MEETING DETAIL
# =========================================================

@app.route(
    "/meeting/<int:meeting_id>"
)
def meeting_detail(
    meeting_id
):

    conn = get_db()

    meeting_row = conn.execute(
        """
        SELECT *
        FROM meetings
        WHERE id = ?
        """,
        (meeting_id,)
    ).fetchone()

    if not meeting_row:

        conn.close()

        return (
            "Meeting not found.",
            404
        )

    tasks = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE meeting_id = ?
        ORDER BY id DESC
        """,
        (meeting_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "transcription.html",
        meeting=meeting_row,
        tasks=tasks
    )


# =========================================================
# ANALYZE MEETING
# =========================================================

@app.route(
    "/analyze",
    methods=["GET", "POST"]
)
def analyze():

    meeting_id = request.values.get(
        "meeting_id",
        type=int
    )

    if not meeting_id:

        return (
            "Meeting ID missing.",
            400
        )

    conn = get_db()

    meeting_row = conn.execute(
        """
        SELECT *
        FROM meetings
        WHERE id = ?
        """,
        (meeting_id,)
    ).fetchone()

    if not meeting_row:

        conn.close()

        return (
            "Meeting not found.",
            404
        )

    transcript = (
        meeting_row["transcript"]
        or ""
    ).strip()

    # -----------------------------------------------------
    # Extract tasks
    # -----------------------------------------------------

    tasks = extract_tasks(
        transcript
    )

    # -----------------------------------------------------
    # Delete old analysis
    # -----------------------------------------------------

    conn.execute(
        """
        DELETE FROM tasks
        WHERE meeting_id = ?
        """,
        (meeting_id,)
    )

    # -----------------------------------------------------
    # Insert fresh tasks
    # -----------------------------------------------------

    for item in tasks:

        conn.execute(
            """
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
            """,
            (
                meeting_id,
                item["task"],
                item["owner"],
                item["deadline"],
                item["priority"],
                "Pending"
            )
        )

    # -----------------------------------------------------
    # Update summary
    # -----------------------------------------------------

    summary = generate_summary(
        transcript
    )

    conn.execute(
        """
        UPDATE meetings
        SET summary = ?
        WHERE id = ?
        """,
        (
            summary,
            meeting_id
        )
    )

    conn.commit()

    conn.close()

    print(
        f"Meeting {meeting_id} analyzed."
    )

    print(
        f"Tasks detected: {len(tasks)}"
    )

    # =====================================================
    # IMPORTANT:
    # After analysis go to Dashboard.
    # =====================================================

    return redirect(
        "/dashboard"
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    conn = get_db()

    tasks = conn.execute(
        """
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
        """
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        tasks=tasks
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

    conn.execute(
        """
        UPDATE tasks
        SET owner = ?
        WHERE id = ?
        """,
        (
            owner,
            task_id
        )
    )

    conn.commit()

    conn.close()

    return redirect(
        "/dashboard"
    )


# =========================================================
# COMPLETE TASK
# =========================================================

@app.route(
    "/complete/<int:task_id>",
    methods=["GET", "POST"]
)
def complete_task(task_id):

    conn = get_db()

    row = conn.execute(
        """
        SELECT status
        FROM tasks
        WHERE id = ?
        """,
        (task_id,)
    ).fetchone()

    if row:

        current_status = (
            row["status"]
            or "Pending"
        )

        if current_status == "Completed":

            new_status = "Pending"

        else:

            new_status = "Completed"

        conn.execute(
            """
            UPDATE tasks
            SET status = ?
            WHERE id = ?
            """,
            (
                new_status,
                task_id
            )
        )

    conn.commit()

    conn.close()

    return redirect(
        "/dashboard"
    )


# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def history():

    conn = get_db()

    meetings = conn.execute(
        """
        SELECT *
        FROM meetings
        ORDER BY id DESC
        """
    ).fetchall()

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

    tasks = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE status != 'Completed'
        AND deadline != 'Not specified'
        ORDER BY id DESC
        """
    ).fetchall()

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

    problems_list = conn.execute(
        """
        SELECT *
        FROM problems
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "problems.html",
        problems=problems_list
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "Meet2ActionAI"
    })


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(413)
def too_large(e):

    return (
        "File too large. Maximum size is 25 MB.",
        413
    )


@app.errorhandler(404)
def not_found(e):

    return (
        "Page not found.",
        404
    )


# =========================================================
# STARTUP
# =========================================================

init_db()

cleanup_old_tasks()


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":

    print("")
    print("======================================")
    print("      Meet2ActionAI is starting")
    print("======================================")
    print("")

    # Render provides PORT automatically.
    # Local development uses 5000.

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