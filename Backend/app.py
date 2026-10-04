from flask import Flask, render_template, request, redirect
import sqlite3
import re
import os
from datetime import datetime
from faster_whisper import WhisperModel

app = Flask(__name__)
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Whisper AI model
model = WhisperModel("base", device="cpu", compute_type="int8")


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect("meet2action.db")
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
            solution TEXT,
            status TEXT DEFAULT 'Open'
        )
    """)

    conn.commit()
    conn.close()


init_db()


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# --------------------------------------------------
# MEETING
# --------------------------------------------------

@app.route("/meeting", methods=["GET", "POST"])
def meeting():

    if request.method == "POST":

        title = request.form.get("meeting_title", "Meeting")
        participants = request.form.get("participants", "")
        transcript = request.form.get("transcript", "")

        # Summary
        sentences = re.split(r"[.!?]+", transcript)
        sentences = [s.strip() for s in sentences if s.strip()]

        summary = ". ".join(sentences[:3])

        # Action words
        action_words = [
            "complete",
            "prepare",
            "finish",
            "submit",
            "create",
            "test",
            "design",
            "develop",
            "check",
            "update",
            "send",
            "review",
            "make",
            "build",
            "work",
            "fix",
            "present",
            "implement",
            "upload",
            "research",
            "discuss"
        ]

        # People
        known_people = [
            "Dharshan",
            "Arun",
            "Praveen",
            "Karthik",
            "Sanjay",
            "Vijay",
            "Ajay",
            "Rahul"
        ]

        conn = get_db()
        cursor = conn.cursor()

        # Save meeting
        cursor.execute("""
            INSERT INTO meetings
            (title, participants, transcript, summary, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            title,
            participants,
            transcript,
            summary,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        meeting_id = cursor.lastrowid

        # Extract tasks
        for sentence in sentences:

            sentence_lower = sentence.lower()

            if not any(word in sentence_lower for word in action_words):
                continue

            # Owner
            owner = "Unassigned"

            for person in known_people:
                if person.lower() in sentence_lower:
                    owner = person
                    break

            # Deadline
            deadline = "Not specified"

            if "tomorrow" in sentence_lower:
                deadline = "Tomorrow"

            elif "today" in sentence_lower:
                deadline = "Today"

            elif "next week" in sentence_lower:
                deadline = "Next Week"

            else:

                date_match = re.search(
                    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
                    sentence
                )

                if date_match:
                    deadline = date_match.group(1)

                else:

                    month_match = re.search(
                        r"\b(january|february|march|april|may|june|july|"
                        r"august|september|october|november|december)"
                        r"\s+\d{1,2}\b",
                        sentence_lower
                    )

                    if month_match:
                        deadline = month_match.group(0).title()

            # Priority
            if any(word in sentence_lower for word in [
                "urgent",
                "critical",
                "high priority",
                "important",
                "asap"
            ]):
                priority = "High"

            elif any(word in sentence_lower for word in [
                "medium",
                "soon",
                "this week"
            ]):
                priority = "Medium"

            else:
                priority = "Low"

            cursor.execute("""
                INSERT INTO tasks
                (meeting_id, task, owner, deadline, priority)
                VALUES (?, ?, ?, ?, ?)
            """, (
                meeting_id,
                sentence,
                owner,
                deadline,
                priority
            ))

        conn.commit()
        conn.close()

        return redirect(f"/meeting/{meeting_id}")

    return render_template("meeting.html")


# --------------------------------------------------
# MEETING DETAILS
# --------------------------------------------------

@app.route("/meeting/<int:meeting_id>")
def meeting_details(meeting_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM meetings WHERE id = ?",
        (meeting_id,)
    )

    meeting_data = cursor.fetchone()

    cursor.execute(
        "SELECT * FROM tasks WHERE meeting_id = ?",
        (meeting_id,)
    )

    tasks = cursor.fetchall()

    conn.close()

    return render_template(
        "meeting.html",
        meeting=meeting_data,
        tasks=tasks
    )


# --------------------------------------------------
# HISTORY
# --------------------------------------------------

@app.route("/history")
def history():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM meetings ORDER BY id DESC"
    )

    meetings = cursor.fetchall()

    conn.close()

    return render_template(
        "history.html",
        meetings=meetings
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM tasks ORDER BY id DESC"
    )

    tasks = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'Pending'"
    )

    pending = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'Completed'"
    )

    completed = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM meetings"
    )

    meetings_count = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "dashboard.html",
        tasks=tasks,
        pending=pending,
        completed=completed,
        meetings_count=meetings_count
    )


# --------------------------------------------------
# COMPLETE TASK
# --------------------------------------------------

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

    return redirect("/dashboard")


# --------------------------------------------------
# NOTIFICATIONS
# --------------------------------------------------

@app.route("/notifications")
def notifications():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM tasks
        WHERE status = 'Pending'
        AND (
            priority = 'High'
            OR deadline = 'Today'
            OR deadline = 'Tomorrow'
        )
        ORDER BY id DESC
    """)

    notifications_data = cursor.fetchall()

    conn.close()

    return render_template(
        "notifications.html",
        notifications=notifications_data
    )


# --------------------------------------------------
# AUDIO UPLOAD
# --------------------------------------------------

@app.route("/upload_audio", methods=["POST"])
def upload_audio():

    audio = request.files.get("audio")

    if not audio or audio.filename == "":
        return "No audio file received."

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        audio.filename
    )

    audio.save(filepath)

    try:

        segments, info = model.transcribe(filepath)

        transcript = " ".join(
            segment.text.strip()
            for segment in segments
        )

        if not transcript:
            transcript = "No speech detected."

        return render_template(
            "transcription.html",
            transcript=transcript
        )

    except Exception as e:

        return f"Transcription error: {str(e)}"


# --------------------------------------------------
# AI ANALYZE API
# --------------------------------------------------

@app.route("/analyze", methods=["POST"])
def analyze():

    audio = request.files.get("file")

    if not audio or audio.filename == "":
        return {
            "error": "No audio file received."
        }, 400

    filename = audio.filename

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    audio.save(filepath)

    try:

        # Speech to text
        segments, info = model.transcribe(filepath)

        transcript = " ".join(
            segment.text.strip()
            for segment in segments
        )

        if not transcript:
            transcript = "No speech detected."

        # Split transcript
        sentences = re.split(
            r"[.!?]+",
            transcript
        )

        sentences = [
            s.strip()
            for s in sentences
            if s.strip()
        ]

        # Action words
        action_words = [
            "complete",
            "prepare",
            "finish",
            "submit",
            "create",
            "test",
            "design",
            "develop",
            "check",
            "update",
            "send",
            "review",
            "make",
            "build",
            "work",
            "fix",
            "present",
            "implement",
            "upload",
            "research",
            "discuss"
        ]

        # Known people
        known_people = [
            "Dharshan",
            "Arun",
            "Praveen",
            "Karthik",
            "Sanjay",
            "Vijay",
            "Ajay",
            "Rahul"
        ]

        tasks = []

        # Extract task information
        for sentence in sentences:

            sentence_lower = sentence.lower()

            # Check whether sentence contains an action
            if not any(
                word in sentence_lower
                for word in action_words
            ):
                continue

            # Person
            owner = "Unassigned"

            for person in known_people:

                if person.lower() in sentence_lower:
                    owner = person
                    break

            # Deadline
            deadline = "Not specified"

            if "tomorrow" in sentence_lower:

                deadline = "Tomorrow"

            elif "today" in sentence_lower:

                deadline = "Today"

            elif "next week" in sentence_lower:

                deadline = "Next Week"

            else:

                date_match = re.search(
                    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
                    sentence
                )

                if date_match:

                    deadline = date_match.group(1)

                else:

                    month_match = re.search(
                        r"\b(january|february|march|april|may|june|july|"
                        r"august|september|october|november|december)"
                        r"\s+\d{1,2}\b",
                        sentence_lower
                    )

                    if month_match:

                        deadline = month_match.group(0).title()

            # Priority
            if any(
                word in sentence_lower
                for word in [
                    "urgent",
                    "critical",
                    "high priority",
                    "important",
                    "asap"
                ]
            ):

                priority = "High"

            elif any(
                word in sentence_lower
                for word in [
                    "medium",
                    "soon",
                    "this week"
                ]
            ):

                priority = "Medium"

            else:

                priority = "Low"

            tasks.append({
                "person": owner,
                "task": sentence,
                "deadline": deadline,
                "priority": priority
            })

        # Return result to frontend
        return {
            "result": transcript,
            "language": info.language,
            "tasks": tasks
        }

    except Exception as e:

        return {
            "error": str(e)
        }, 500


# --------------------------------------------------
# RUN SERVER
# --------------------------------------------------

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )