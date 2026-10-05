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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_NAME = os.path.join(BASE_DIR, "meet2action.db")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "mp3",
    "wav",
    "m4a",
    "mp4",
    "webm",
    "ogg",
    "mpeg",
    "mpga"
}

# ============================================================
# TEAM MEMBERS
# ============================================================

PEOPLE = [
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

# ============================================================
# WHISPER
# ============================================================

print("Loading Whisper model...")

model = WhisperModel(
    "tiny",
    device="cpu",
    compute_type="int8",
    cpu_threads=1,
    num_workers=1
)

print("Whisper model loaded successfully.")

# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            transcript TEXT,
            summary TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            problem TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def allowed_file(filename):

    if not filename:
        return False

    if "." not in filename:
        return False

    ext = filename.rsplit(".", 1)[1].lower()

    return ext in ALLOWED_EXTENSIONS


def clean_text(text):

    if not text:
        return ""

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_task(text):

    text = clean_text(text)

    text = re.sub(
        r"^(task|action item|action|todo)\s*[:\-]\s*",
        "",
        text,
        flags=re.I
    )

    text = re.sub(
        r"^(please|kindly)\s+",
        "",
        text,
        flags=re.I
    )

    text = text.strip(" .,!?:;-")

    if text:
        text = text[0].upper() + text[1:]

    return text


# ============================================================
# OWNER DETECTION
# ============================================================

def detect_owner(text):

    original = clean_text(text)

    lower = original.lower()

    # --------------------------------------------------------
    # FIRST PERSON
    # --------------------------------------------------------

    if re.search(
        r"^\s*(i|i'll|i will|i can|i'm going to|i am going to|i am|i'm)\b",
        lower
    ):
        return "Self"

    # --------------------------------------------------------
    # NAME + WILL
    # Examples:
    # Priya will test the application
    # Arun will complete website
    # Dharshan will prepare presentation
    # --------------------------------------------------------

    match = re.match(
        r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s+will\b",
        original,
        flags=re.I
    )

    if match:
        return match.group(1).strip().title()

    # --------------------------------------------------------
    # NAME + CAN
    # Example:
    # Priya can test the application
    # --------------------------------------------------------

    match = re.match(
        r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s+can\b",
        original,
        flags=re.I
    )

    if match:
        return match.group(1).strip().title()

    # --------------------------------------------------------
    # NAME + SHOULD
    # Example:
    # Arun should prepare report
    # --------------------------------------------------------

    match = re.match(
        r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s+should\b",
        original,
        flags=re.I
    )

    if match:
        return match.group(1).strip().title()

    # --------------------------------------------------------
    # ASSIGNED TO
    # --------------------------------------------------------

    match = re.search(
        r"(?:assigned to|assign to|responsible to|handled by|owned by)\s+([A-Za-z][A-Za-z0-9_-]*)",
        original,
        flags=re.I
    )

    if match:
        return match.group(1).strip().title()

    # --------------------------------------------------------
    # FIXED TEAM MEMBERS FALLBACK
    # --------------------------------------------------------

    for person in PEOPLE:

        if re.search(
            rf"\b{re.escape(person)}\b",
            original,
            flags=re.I
        ):
            return person

    return "Unassigned"


# ============================================================
# DEADLINE DETECTION
# ============================================================

def detect_deadline(text):

    original = clean_text(text)
    lower = original.lower()

    # --------------------------------------------------------
    # TOMORROW
    # --------------------------------------------------------

    if re.search(r"\btomorrow\b", lower):
        return "Tomorrow"

    # --------------------------------------------------------
    # TODAY
    # --------------------------------------------------------

    if re.search(r"\btoday\b", lower):
        return "Today"

    # --------------------------------------------------------
    # TONIGHT
    # --------------------------------------------------------

    if re.search(r"\btonight\b", lower):
        return "Tonight"

    # --------------------------------------------------------
    # THIS WEEK
    # --------------------------------------------------------

    if re.search(r"\bthis week\b", lower):
        return "This Week"

    # --------------------------------------------------------
    # NEXT WEEK
    # --------------------------------------------------------

    if re.search(r"\bnext week\b", lower):
        return "Next Week"

    # --------------------------------------------------------
    # WEEKDAYS
    # --------------------------------------------------------

    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    ]

    for day in weekdays:

        if re.search(
            rf"\b{day}\b",
            original,
            flags=re.I
        ):
            return day

    # --------------------------------------------------------
    # MONTH + DATE
    #
    # October 7
    # October 10
    # by October 8
    # on October 12
    # --------------------------------------------------------

    months = (
        "January|February|March|April|May|June|July|"
        "August|September|October|November|December"
    )

    match = re.search(
        rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        original,
        flags=re.I
    )

    if match:

        month = match.group(1).capitalize()
        day = match.group(2)

        return f"{month} {day}"

    # --------------------------------------------------------
    # DATE + MONTH
    #
    # 7 October
    # 10 October
    # --------------------------------------------------------

    match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})\b",
        original,
        flags=re.I
    )

    if match:

        day = match.group(1)
        month = match.group(2).capitalize()

        return f"{month} {day}"

    # --------------------------------------------------------
    # NUMERIC DATE
    #
    # 10/10
    # 10-10
    # --------------------------------------------------------

    match = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b",
        original
    )

    if match:

        day = match.group(1)
        month = match.group(2)

        if match.group(3):
            year = match.group(3)
            return f"{day}/{month}/{year}"

        return f"{day}/{month}"

    return "Not specified"


# ============================================================
# PRIORITY
# ============================================================

def detect_priority(text):

    lower = clean_text(text).lower()

    high_words = [
        "urgent",
        "critical",
        "important",
        "immediately",
        "asap",
        "high priority",
        "fix bug",
        "fix issue",
        "resolve issue",
        "production issue"
    ]

    medium_words = [
        "soon",
        "important task",
        "medium priority"
    ]

    for word in high_words:

        if word in lower:
            return "High"

    for word in medium_words:

        if word in lower:
            return "Medium"

    return "Normal"


# ============================================================
# SUMMARY
# ============================================================

def generate_summary(transcript):

    transcript = clean_text(transcript)

    if not transcript:
        return "No transcript available."

    sentences = re.split(
        r"(?<=[.!?])\s+",
        transcript
    )

    sentences = [
        s.strip()
        for s in sentences
        if s.strip()
    ]

    if len(sentences) <= 4:
        return " ".join(sentences)

    return " ".join(sentences[:4])


# ============================================================
# TASK EXTRACTION
# ============================================================

def extract_tasks(transcript, meeting_id):

    if not transcript:
        return []

    text = clean_text(transcript)

    # Split transcript into sentences
    sentences = re.split(
        r"(?<=[.!?])\s+|(?<=\n)",
        text
    )

    tasks_created = []
    seen = set()

    conn = get_db()

    # --------------------------------------------------------
    # ACTION PATTERNS
    # --------------------------------------------------------

    action_patterns = [
        r"\bwill\b",
        r"\bcan\b",
        r"\bi'll\b",
        r"\bi will\b",
        r"\bi can\b",
        r"\blet's\b",
        r"\bneed to\b",
        r"\bneeds to\b",
        r"\bassigned to\b",
        r"\bresponsible for\b",
        r"\bcomplete\b",
        r"\bprepare\b",
        r"\bcreate\b",
        r"\bdesign\b",
        r"\bdevelop\b",
        r"\bbuild\b",
        r"\btest\b",
        r"\bfix\b",
        r"\bsubmit\b",
        r"\bupdate\b",
        r"\bcollect\b",
        r"\bresearch\b",
        r"\borganize\b",
        r"\breview\b",
        r"\bpresent\b",
        r"\bdocument\b",
        r"\banalyze\b"
    ]

    # --------------------------------------------------------
    # GENERIC / JUNK PHRASES
    # --------------------------------------------------------

    junk_patterns = [
        r"where should i go",
        r"what should we do",
        r"how should we",
        r"i think",
        r"i guess",
        r"maybe we",
        r"we should discuss",
        r"we should talk",
        r"we need to discuss",
        r"we need to talk",
        r"communication will be",
        r"we should share updates",
        r"update the team about our progress",
        r"that gives us enough time",
        r"when should we finish",
        r"when do we finish",
        r"what do you think"
    ]

    for sentence in sentences:

        sentence = clean_text(sentence)

        if not sentence:
            continue

        lower = sentence.lower()

        # ----------------------------------------------------
        # SKIP QUESTIONS
        # ----------------------------------------------------

        if "?" in sentence:
            continue

        if re.match(
            r"^(what|why|when|where|who|how|which|can we|should we)\b",
            lower
        ):
            continue

        # ----------------------------------------------------
        # SKIP JUNK
        # ----------------------------------------------------

        skip = False

        for pattern in junk_patterns:

            if re.search(pattern, lower):
                skip = True
                break

        if skip:
            continue

        # ----------------------------------------------------
        # MUST LOOK LIKE AN ACTION
        # ----------------------------------------------------

        is_action = False

        for pattern in action_patterns:

            if re.search(pattern, lower):
                is_action = True
                break

        if not is_action:
            continue

        # ----------------------------------------------------
        # REMOVE VAGUE SENTENCES
        # ----------------------------------------------------

        if re.match(
            r"^(we|it|this|that)\s+(will|would|could|should)\s+be\b",
            lower
        ):
            continue

        # ----------------------------------------------------
        # NORMALIZE TASK
        # ----------------------------------------------------

        task_text = normalize_task(sentence)

        if not task_text:
            continue

        # ----------------------------------------------------
        # REMOVE PURE DISCUSSION SENTENCES
        # ----------------------------------------------------

        if len(task_text.split()) < 3:
            continue

        # ----------------------------------------------------
        # FIRST PERSON PREFIX
        # ----------------------------------------------------

        task_text = re.sub(
            r"^(I|I'll|I will|I can|I'm going to|I am going to)\s+",
            "",
            task_text,
            flags=re.I
        )

        # ----------------------------------------------------
        # TEAM PREFIX
        # ----------------------------------------------------

        task_text = re.sub(
            r"^(we will|we can|we need to|we have to|let's)\s+",
            "",
            task_text,
            flags=re.I
        )

        task_text = task_text.strip()

        if not task_text:
            continue

        task_text = task_text[0].upper() + task_text[1:]

        # ----------------------------------------------------
        # REMOVE TRAILING punctuation
        # ----------------------------------------------------

        task_text = task_text.rstrip(" .,!?:;-")

        # ----------------------------------------------------
        # FINAL JUNK CHECK
        # ----------------------------------------------------

        if len(task_text.split()) < 3:
            continue

        # ----------------------------------------------------
        # OWNER
        # ----------------------------------------------------

        owner = detect_owner(sentence)

        # ----------------------------------------------------
        # DEADLINE
        # ----------------------------------------------------

        deadline = detect_deadline(sentence)

        # ----------------------------------------------------
        # PRIORITY
        # ----------------------------------------------------

        priority = detect_priority(sentence)

        # ----------------------------------------------------
        # DEDUPLICATE WITHIN CURRENT MEETING
        # ----------------------------------------------------

        key = task_text.lower().strip()

        if key in seen:
            continue

        seen.add(key)

        # ----------------------------------------------------
        # DEDUPLICATE SAME TASK FOR SAME MEETING
        # ----------------------------------------------------

        existing = conn.execute(
            """
            SELECT id
            FROM tasks
            WHERE meeting_id = ?
            AND LOWER(TRIM(task)) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (meeting_id, task_text)
        ).fetchone()

        if existing:
            continue

        # ----------------------------------------------------
        # INSERT
        # ----------------------------------------------------

        cursor = conn.execute(
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
                task_text,
                owner,
                deadline,
                priority,
                "Pending"
            )
        )

        task_id = cursor.lastrowid

        tasks_created.append({
            "id": task_id,
            "meeting_id": meeting_id,
            "task": task_text,
            "owner": owner,
            "deadline": deadline,
            "priority": priority,
            "status": "Pending"
        })

    conn.commit()
    conn.close()

    return tasks_created


# ============================================================
# CLEAN OLD JUNK DATA
# ============================================================

def cleanup_old_tasks():

    conn = get_db()

    # Remove questions
    conn.execute("""
        DELETE FROM tasks
        WHERE task LIKE '%?%'
    """)

    # Remove obvious junk
    junk_words = [
        "Where should I go",
        "I think communication",
        "We should share updates regularly",
        "update the team about our progress",
        "That gives us enough time",
        "When should we finish",
        "What should we do"
    ]

    for word in junk_words:

        conn.execute(
            """
            DELETE FROM tasks
            WHERE LOWER(task) LIKE ?
            """,
            (f"%{word.lower()}%",)
        )

    # Remove exact duplicate tasks
    conn.execute("""
        DELETE FROM tasks
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM tasks
            GROUP BY LOWER(TRIM(task))
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# PARTICIPANTS
# ============================================================

def detect_participants(transcript):

    found = []

    if not transcript:
        return found

    for person in PEOPLE:

        if re.search(
            rf"\b{re.escape(person)}\b",
            transcript,
            flags=re.I
        ):
            found.append(person)

    return found


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template("index.html")


# ============================================================
# UPLOAD AUDIO
# ============================================================

@app.route("/upload_audio", methods=["POST"])
def upload_audio():

    if "audio" not in request.files:

        return jsonify({
            "success": False,
            "error": "No audio file uploaded."
        }), 400

    file = request.files["audio"]

    if not file.filename:

        return jsonify({
            "success": False,
            "error": "Please select an audio file."
        }), 400

    if not allowed_file(file.filename):

        return jsonify({
            "success": False,
            "error": "Unsupported audio format."
        }), 400

    unique_name = (
        str(uuid.uuid4())
        + "_"
        + file.filename
    )

    filepath = os.path.join(
        UPLOAD_FOLDER,
        unique_name
    )

    file.save(filepath)

    print("Audio saved:", filepath)
    print("Starting transcription...")

    try:

        segments, info = model.transcribe(
            filepath,
            beam_size=1,
            best_of=1,
            temperature=0,
            vad_filter=True,
            condition_on_previous_text=False
        )

        transcript_parts = []

        for segment in segments:

            segment_text = clean_text(segment.text)

            if segment_text:
                transcript_parts.append(segment_text)

        transcript = " ".join(transcript_parts)

        transcript = clean_text(transcript)

        print("Transcription completed.")

    except Exception as e:

        print("Transcription error:", e)

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    # --------------------------------------------------------
    # CREATE MEETING
    # --------------------------------------------------------

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO meetings
        (
            filename,
            transcript,
            summary,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            file.filename,
            transcript,
            generate_summary(transcript),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    meeting_id = cursor.lastrowid

    conn.commit()
    conn.close()

    # --------------------------------------------------------
    # EXTRACT TASKS
    # --------------------------------------------------------

    extract_tasks(
        transcript,
        meeting_id
    )

    # --------------------------------------------------------
    # REMOVE FILE AFTER TRANSCRIPTION
    # --------------------------------------------------------

    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

    return redirect(
        f"/meeting/{meeting_id}"
    )


# ============================================================
# MEETING PAGE
# ============================================================

@app.route("/meeting/<int:meeting_id>")
def meeting(meeting_id):

    conn = get_db()

    meeting_data = conn.execute(
        """
        SELECT *
        FROM meetings
        WHERE id = ?
        """,
        (meeting_id,)
    ).fetchone()

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

    if not meeting_data:

        return "Meeting not found", 404

    return render_template(
        "transcription.html",
        meeting=meeting_data,
        tasks=tasks
    )


# ============================================================
# OLD /MEETING POST SUPPORT
# ============================================================

@app.route("/meeting", methods=["POST"])
def meeting_post():

    return redirect("/dashboard")


# ============================================================
# UPDATE OWNER
# ============================================================

@app.route("/update_owner/<int:task_id>", methods=["POST"])
def update_owner(task_id):

    owner = request.form.get("owner", "").strip()

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

    return redirect("/dashboard")


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    cleanup_old_tasks()

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
        LIMIT 100
        """
    ).fetchall()

    meetings = conn.execute(
        """
        SELECT *
        FROM meetings
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    total_tasks = len(tasks)

    completed_tasks = sum(
        1
        for task in tasks
        if str(task["status"]).lower() == "completed"
    )

    pending_tasks = total_tasks - completed_tasks

    high_priority = sum(
        1
        for task in tasks
        if str(task["priority"]).lower() == "high"
    )

    return render_template(
        "dashboard.html",
        tasks=tasks,
        meetings=meetings,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        high_priority=high_priority
    )


# ============================================================
# MARK COMPLETED
# ============================================================

@app.route("/complete/<int:task_id>")
def complete_task(task_id):

    conn = get_db()

    conn.execute(
        """
        UPDATE tasks
        SET status = 'Completed'
        WHERE id = ?
        """,
        (task_id,)
    )

    conn.commit()
    conn.close()

    return redirect("/dashboard")


# ============================================================
# HISTORY
# ============================================================

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


# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route("/notifications")
def notifications():

    conn = get_db()

    tasks = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE status != 'Completed'
        ORDER BY id DESC
        """
    ).fetchall()

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

    problems_data = conn.execute(
        """
        SELECT *
        FROM problems
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "problems.html",
        problems=problems_data
    )


# ============================================================
# ANALYZE
# ============================================================

@app.route("/analyze", methods=["POST"])
def analyze():

    # --------------------------------------------------------
    # If meeting ID is provided, use existing meeting
    # --------------------------------------------------------

    meeting_id = request.form.get("meeting_id")

    if meeting_id:

        try:
            meeting_id = int(meeting_id)
        except ValueError:
            meeting_id = None

    if meeting_id:

        conn = get_db()

        meeting_data = conn.execute(
            """
            SELECT *
            FROM meetings
            WHERE id = ?
            """,
            (meeting_id,)
        ).fetchone()

        conn.close()

        if meeting_data:

            extract_tasks(
                meeting_data["transcript"],
                meeting_id
            )

    return redirect("/dashboard")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "app": "Meet2ActionAI"
    })


# ============================================================
# STARTUP
# ============================================================

init_db()
cleanup_old_tasks()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )