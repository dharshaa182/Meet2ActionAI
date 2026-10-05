from flask import Flask, render_template, request, redirect
import sqlite3
import re
import os
from datetime import datetime
from faster_whisper import WhisperModel

app = Flask(__name__)

# ==================================================
# CORS
# ==================================================

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ==================================================
# UPLOAD SETTINGS
# ==================================================

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ==================================================
# WHISPER
# ==================================================

model = None


def get_whisper_model():
    global model

    if model is None:
        print("Loading Whisper model...")

        model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )

        print("Whisper model loaded.")

    return model


# ==================================================
# DATABASE
# ==================================================

DATABASE = "meet2action.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
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


# ==================================================
# PEOPLE
# ==================================================

KNOWN_PEOPLE = [
    "Dharshan",
    "Mubeen",
    "Bala",
    "Pugazhendhi",
    "Naveen",
    "Arun",
    "Kumar",
    "Praveen",
    "Karthik",
    "Sanjay",
    "Vijay",
    "Ajay",
    "Rahul",
    "Priya"
]


def detect_owner(sentence):

    for person in KNOWN_PEOPLE:

        if re.search(
            r"\b" + re.escape(person) + r"\b",
            sentence,
            re.IGNORECASE
        ):
            return person

    return "Unassigned"


# ==================================================
# DEADLINE
# ==================================================

def detect_deadline(sentence):

    text = sentence.lower()

    if re.search(r"\btoday\b", text):
        return "Today"

    if re.search(r"\btomorrow\b", text):
        return "Tomorrow"

    if re.search(r"\bnext week\b", text):
        return "Next Week"

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

        if re.search(r"\b" + day + r"\b", text):
            return day.title()

    date_match = re.search(
        r"\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
        sentence
    )

    if date_match:
        return date_match.group(1)

    months = (
        "january|february|march|april|may|june|july|"
        "august|september|october|november|december"
    )

    month_match = re.search(
        r"\b(" + months + r")\s+(\d{1,2})\b",
        text
    )

    if month_match:

        return (
            month_match.group(1).title()
            + " "
            + month_match.group(2)
        )

    return "Not specified"


# ==================================================
# PRIORITY
# ==================================================

def detect_priority(sentence):

    text = sentence.lower()

    high_words = [
        "urgent",
        "critical",
        "high priority",
        "very important",
        "immediately",
        "as soon as possible"
    ]

    medium_words = [
        "important",
        "medium priority"
    ]

    for word in high_words:

        if word in text:
            return "High"

    for word in medium_words:

        if word in text:
            return "Medium"

    return "Low"


# ==================================================
# SUMMARY
# ==================================================

def generate_summary(transcript):

    sentences = re.split(
        r"(?<=[.!?])\s+|\n+",
        transcript.strip()
    )

    important = []

    keywords = [
        "main goal",
        "project",
        "prepare",
        "research",
        "presentation",
        "complete",
        "finish",
        "deadline",
        "update",
        "progress",
        "communication"
    ]

    ignored = [
        "good morning",
        "good afternoon",
        "good evening",
        "are we ready",
        "yes, i'm ready",
        "let's begin",
        "i'm interested",
        "what should we focus",
        "first, we need to divide the tasks",
        "that sounds good",
        "we can work together",
        "excellent",
        "everyone has a clear responsibility",
        "when should we finish",
        "that gives us enough time",
        "agreed",
        "i think communication",
        "absolutely",
        "that's exactly right",
        "good teamwork",
        "we'll make sure everyone stays informed",
        "great work",
        "let's start working",
        "thank you",
        "i'm ready to get started",
        "me too",
        "let's make this project successful",
        "see you"
    ]

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        lower = sentence.lower()

        if sentence.endswith("?"):
            continue

        if any(x in lower for x in ignored):
            continue

        if any(x in lower for x in keywords):
            important.append(sentence)

    unique = []

    for sentence in important:

        if sentence not in unique:
            unique.append(sentence)

    if not unique:
        return "No meeting summary available."

    return " ".join(unique[:4])


# ==================================================
# TASK EXTRACTION
# ==================================================

def extract_tasks(transcript):

    tasks = []

    sentences = re.split(
        r"(?<=[.!?])\s+|\n+",
        transcript.strip()
    )

    ignored = [
        "good morning",
        "good afternoon",
        "good evening",
        "are we ready",
        "yes, i'm ready",
        "let's begin",
        "i'm interested",
        "what should we focus",
        "that sounds good",
        "we can work together",
        "excellent",
        "everyone has a clear responsibility",
        "first, we need to divide the tasks",
        "agreed",
        "that gives us enough time",
        "i think communication",
        "absolutely",
        "that's exactly right",
        "good teamwork",
        "we'll make sure everyone stays informed",
        "great work",
        "let's start working",
        "thank you",
        "i'm ready to get started",
        "me too",
        "let's make this project successful",
        "see you"
    ]

    patterns = [
        r"\b[A-Za-z]+\s+will\s+",

        r"\bI\s+can\s+"
        r"(prepare|create|develop|design|organize|collect|"
        r"complete|finish|test|check|update|submit|send|review|help)\b",

        r"\bI'll\s+"
        r"(prepare|create|develop|design|organize|collect|"
        r"complete|finish|test|check|update|submit|send|review|help)\b",

        r"\bshould\s+"
        r"(update|share|complete|check|prepare|submit|review|organize)\b",

        r"\bmust\b",
        r"\bneed to\b",
        r"\bneeds to\b",
        r"\bhas to\b",
        r"\bhave to\b",

        r"\bLet's\s+"
        r"(complete|prepare|create|finish|check|update|submit)\b"
    ]

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        if sentence.endswith("?"):
            continue

        lower = sentence.lower()

        if any(x in lower for x in ignored):
            continue

        is_task = False

        for pattern in patterns:

            if re.search(
                pattern,
                sentence,
                re.IGNORECASE
            ):
                is_task = True
                break

        if not is_task:
            continue

        tasks.append({
            "task": sentence,
            "owner": detect_owner(sentence),
            "deadline": detect_deadline(sentence),
            "priority": detect_priority(sentence)
        })

    return tasks


# ==================================================
# HOME
# ==================================================

@app.route("/")
def index():
    return render_template("index.html")


# ==================================================
# MEETING
# ==================================================

@app.route("/meeting", methods=["GET", "POST"])
def meeting():

    if request.method == "GET":
        return render_template("meeting.html")

    title = request.form.get(
        "title",
        "Untitled Meeting"
    )

    participants = request.form.get(
        "participants",
        ""
    )

    transcript = request.form.get(
        "transcript",
        ""
    )

    summary = request.form.get(
        "summary",
        ""
    ).strip()

    if not summary:
        summary = generate_summary(transcript)

    conn = get_db()
    cursor = conn.cursor()

    created_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

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
        transcript,
        summary,
        created_at
    ))

    meeting_id = cursor.lastrowid

    extracted_tasks = extract_tasks(transcript)

    for item in extracted_tasks:

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
            item["task"],
            item["owner"],
            item["deadline"],
            item["priority"],
            "Pending"
        ))

    conn.commit()
    conn.close()

    return redirect(
        f"/meeting/{meeting_id}"
    )


# ==================================================
# MEETING DETAILS
# ==================================================

@app.route("/meeting/<int:meeting_id>")
def meeting_details(meeting_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM meetings WHERE id = ?",
        (meeting_id,)
    )

    meeting = cursor.fetchone()

    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE meeting_id = ?
        ORDER BY id ASC
    """, (meeting_id,))

    tasks = cursor.fetchall()

    conn.close()

    if meeting is None:
        return "Meeting not found", 404

    return render_template(
        "meeting_details.html",
        meeting=meeting,
        tasks=tasks
    )


# ==================================================
# UPDATE OWNER
# ==================================================

@app.route(
    "/update_owner/<int:task_id>",
    methods=["POST"]
)
def update_owner(task_id):

    owner = request.form.get(
        "owner",
        "Unassigned"
    ).strip()

    allowed_owners = [
        "Unassigned",
        "Dharshan",
        "Arun",
        "Pugal",
        "Mubeen",
        "Bala",
        "Pugazhendhi",
        "Naveen",
        "Karthik",
        "Rahul"
    ]

    if owner not in allowed_owners:
        owner = "Unassigned"

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
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
        request.referrer or "/"
    )


# ==================================================
# HISTORY
# ==================================================

@app.route("/history")
def history():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM meetings
        ORDER BY id DESC
    """)

    meetings = cursor.fetchall()

    conn.close()

    return render_template(
        "history.html",
        meetings=meetings
    )


# ==================================================
# DASHBOARD
# ==================================================

@app.route("/dashboard")
def dashboard():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM meetings"
    )
    total_meetings = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tasks"
    )
    total_tasks = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status = 'Completed'
    """)
    completed_tasks = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM tasks
        WHERE status != 'Completed'
    """)
    pending_tasks = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "dashboard.html",
        total_meetings=total_meetings,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks
    )


# ==================================================
# COMPLETE TASK
# ==================================================

@app.route("/complete/<int:task_id>")
def complete_task(task_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks
        SET status = 'Completed'
        WHERE id = ?
    """, (task_id,))

    conn.commit()
    conn.close()

    return redirect(
        request.referrer or "/"
    )


# ==================================================
# NOTIFICATIONS
# ==================================================

@app.route("/notifications")
def notifications():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE status != 'Completed'
        ORDER BY id DESC
    """)

    tasks = cursor.fetchall()

    conn.close()

    return render_template(
        "notifications.html",
        tasks=tasks
    )


# ==================================================
# PROBLEMS
# ==================================================

@app.route("/problems")
def problems():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM problems
        ORDER BY id DESC
    """)

    problems_list = cursor.fetchall()

    conn.close()

    return render_template(
        "problems.html",
        problems=problems_list
    )


# ==================================================
# UPLOAD AUDIO
# ==================================================

@app.route(
    "/upload_audio",
    methods=["GET", "POST"]
)
def upload_audio():

    if request.method == "GET":
        return render_template(
            "upload_audio.html"
        )

    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file received"

    if audio_file.filename == "":
        return "Please select an audio file"

    filename = audio_file.filename

    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    audio_file.save(file_path)

    try:

        whisper_model = get_whisper_model()

        segments, info = whisper_model.transcribe(
            file_path
        )

        transcript_parts = []

        for segment in segments:
            transcript_parts.append(
                segment.text.strip()
            )

        transcript = " ".join(
            transcript_parts
        )

    except Exception as e:

        print(
            "Transcription error:",
            e
        )

        return (
            "Transcription error: "
            + str(e)
        )

    return render_template(
        "transcription.html",
        transcript=transcript
    )


# ==================================================
# ANALYZE
# ==================================================

@app.route(
    "/analyze",
    methods=["POST"]
)
def analyze():

    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file received"

    if audio_file.filename == "":
        return "Please select an audio file"

    filename = audio_file.filename

    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    audio_file.save(file_path)

    try:

        whisper_model = get_whisper_model()

        segments, info = whisper_model.transcribe(
            file_path
        )

        transcript_parts = []

        for segment in segments:
            transcript_parts.append(
                segment.text.strip()
            )

        transcript = " ".join(
            transcript_parts
        )

    except Exception as e:

        print(
            "Transcription error:",
            e
        )

        return (
            "Transcription error: "
            + str(e)
        )

    tasks = extract_tasks(transcript)
    summary = generate_summary(transcript)

    return render_template(
        "analysis.html",
        transcript=transcript,
        tasks=tasks,
        summary=summary
    )


# ==================================================
# REPORT
# ==================================================

@app.route("/report")
def report():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM tasks
        ORDER BY id DESC
    """)

    tasks = cursor.fetchall()

    conn.close()

    return render_template(
        "report.html",
        tasks=tasks
    )


# ==================================================
# START
# ==================================================

if __name__ == "__main__":

    print("")
    print("==========================================")
    print("       Meet2Action AI Started")
    print("==========================================")
    print("Open: http://127.0.0.1:5001")
    print("==========================================")
    print("")

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )