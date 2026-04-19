from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
import random
import os
from datetime import datetime, date, timedelta
import json

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "studyplanner2024")

# DB path — works locally and on Render
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────
#  DATABASE INIT
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            subjects   TEXT,
            hours      INTEGER,
            created_at TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT,
            date          TEXT,
            hours_studied REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timetables (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            data       TEXT,
            created_at TEXT DEFAULT ''
        )
    """)
    for col in [("priority", "TEXT DEFAULT ''"), ("created_at", "TEXT DEFAULT ''")]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
        except Exception:
            pass
    conn.commit()
    conn.close()

init_db()

# ─────────────────────────────────────────
#  STUDY TIPS
# ─────────────────────────────────────────
SUBJECT_TIPS = {
    "python":    ["Practice coding daily", "Build small projects", "Read official docs"],
    "math":      ["Solve 10 problems daily", "Understand concepts first", "Use graph paper"],
    "physics":   ["Draw diagrams", "Relate to real life", "Solve numericals daily"],
    "chemistry": ["Learn periodic table", "Practice balancing equations", "Use flashcards"],
    "english":   ["Read newspapers daily", "Write short essays", "Learn 5 new words/day"],
    "history":   ["Make timelines", "Use mnemonics", "Read story-style"],
    "biology":   ["Draw diagrams", "Use color coding", "Relate to body functions"],
    "computer":  ["Practice typing", "Code daily", "Read documentation"],
    "science":   ["Watch experiment videos", "Make concise notes", "Relate to daily life"],
    "default":   ["Stay consistent", "Take short breaks (Pomodoro)", "Review notes daily"],
}

def get_tips(subject):
    key = subject.lower().strip()
    for k in SUBJECT_TIPS:
        if k in key:
            return SUBJECT_TIPS[k]
    return SUBJECT_TIPS["default"]

# ─────────────────────────────────────────
#  STUDY PLAN GENERATOR
# ─────────────────────────────────────────
def generate_plan(subjects, hours, priorities=None):
    subjects_list = [s.strip() for s in subjects.split(",") if s.strip()]
    if not subjects_list:
        return {}
    weight_map = {"high": 3, "medium": 2, "low": 1}
    weights = []
    for sub in subjects_list:
        p = "medium"
        if priorities:
            p = priorities.get(sub.lower(), "medium")
        weights.append(weight_map.get(p, 2))
    total_w = sum(weights)
    plan = {}
    for i, sub in enumerate(subjects_list):
        plan[sub] = round((weights[i] / total_w) * hours, 1)
    return plan

# ─────────────────────────────────────────
#  AI TIMETABLE GENERATOR
# ─────────────────────────────────────────
SLOT_COLORS = [
    "#1a237e", "#1565c0", "#0277bd", "#00695c",
    "#2e7d32", "#558b2f", "#6a1b9a", "#ad1457",
    "#c62828", "#e65100", "#f57f17", "#4527a0",
]

TIME_SLOTS = [
    "6:00 AM", "7:00 AM", "8:00 AM", "9:00 AM",
    "10:00 AM", "11:00 AM", "12:00 PM", "1:00 PM",
    "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM",
    "6:00 PM", "7:00 PM", "8:00 PM", "9:00 PM",
    "10:00 PM",
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def ai_generate_timetable(subjects_raw, daily_hours, wake_time, sleep_time,
                           exam_dates_raw, break_day, goal):
    subjects_list = [s.strip() for s in subjects_raw.split(",") if s.strip()]
    if not subjects_list:
        return None, "Please enter at least one subject."

    today = date.today()

    exam_map = {}
    if exam_dates_raw.strip():
        for entry in exam_dates_raw.split(";"):
            entry = entry.strip()
            if ":" in entry:
                parts = entry.split(":", 1)
                sub_key = parts[0].strip().lower()
                try:
                    exam_map[sub_key] = datetime.strptime(parts[1].strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass

    def urgency(sub):
        key = sub.lower()
        for k, d in exam_map.items():
            if k in key or key in k:
                days_left = (d - today).days
                if days_left <= 0:   return 10
                elif days_left <= 3: return 9
                elif days_left <= 7: return 7
                elif days_left <= 14: return 5
                elif days_left <= 30: return 3
                else: return 2
        return 3 if goal == "exam" else 2

    weights = [urgency(s) for s in subjects_list]
    total_w = sum(weights)

    try:
        wake_h  = int(wake_time.split(":")[0])
        sleep_h = int(sleep_time.split(":")[0])
    except Exception:
        wake_h, sleep_h = 6, 22

    if sleep_h <= wake_h:
        sleep_h = wake_h + 16

    available_slots = [
        t for t in TIME_SLOTS
        if wake_h <= int(t.split(":")[0]) < sleep_h
    ]

    color_map = {sub: SLOT_COLORS[i % len(SLOT_COLORS)] for i, sub in enumerate(subjects_list)}

    timetable = {}
    for day_idx, day in enumerate(DAYS):
        timetable[day] = {}
        if day == break_day:
            for slot in available_slots:
                timetable[day][slot] = {"subject": "🌿 Rest Day", "color": "#78909c", "type": "rest"}
            continue

        slots_to_fill = min(daily_hours, len(available_slots) - 1)
        slot_subjects = []
        for i, sub in enumerate(subjects_list):
            count = max(1, round((weights[i] / total_w) * slots_to_fill))
            slot_subjects.extend([sub] * count)

        slot_subjects = slot_subjects[:slots_to_fill]
        while len(slot_subjects) < slots_to_fill:
            slot_subjects.append(subjects_list[day_idx % len(subjects_list)])

        random.seed(day_idx * 7)
        random.shuffle(slot_subjects)

        if goal in ("exam", "revision") and slots_to_fill > 0:
            slot_subjects[-1] = "📝 Revision"

        filled = 0
        for slot in available_slots:
            if filled < len(slot_subjects):
                sub = slot_subjects[filled]
                if sub == "📝 Revision":
                    timetable[day][slot] = {"subject": "📝 Revision", "color": "#f57c00", "type": "revision"}
                else:
                    timetable[day][slot] = {"subject": sub, "color": color_map.get(sub, "#1a237e"), "type": "study"}
                filled += 1
            else:
                timetable[day][slot] = {"subject": "☕ Break / Free", "color": "#90a4ae", "type": "free"}

    summary = {sub: 0 for sub in subjects_list}
    for day in timetable:
        for slot, info in timetable[day].items():
            if info["type"] == "study" and info["subject"] in summary:
                summary[info["subject"]] += 1

    countdowns = {}
    for sub in subjects_list:
        key = sub.lower()
        for k, d in exam_map.items():
            if k in key or key in k:
                countdowns[sub] = max(0, (d - today).days)

    return {
        "timetable": timetable,
        "slots": available_slots,
        "days": DAYS,
        "subjects": subjects_list,
        "color_map": color_map,
        "summary": summary,
        "countdowns": countdowns,
        "daily_hours": daily_hours,
        "goal": goal,
    }, None

# ─────────────────────────────────────────
#  PDF GENERATOR
# ─────────────────────────────────────────
def create_pdf(plan, name):
    os.makedirs("static", exist_ok=True)
    path = "static/study_plan.pdf"
    doc = SimpleDocTemplate(path, pagesize=letter,
                            rightMargin=inch, leftMargin=inch,
                            topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('T', parent=styles['Title'],
                                 fontSize=22, textColor=colors.HexColor("#1a237e"), spaceAfter=6)
    sub_style   = ParagraphStyle('S', parent=styles['Normal'],
                                 fontSize=11, textColor=colors.HexColor("#555555"), spaceAfter=16)
    tip_style   = ParagraphStyle('Tip', parent=styles['Normal'],
                                 fontSize=9, textColor=colors.HexColor("#2e7d32"), leftIndent=10)
    elements = []
    elements.append(Paragraph("Smart Study Plan", title_style))
    elements.append(Paragraph(
        f"Prepared for: <b>{name}</b>  |  Date: {datetime.now().strftime('%d %B %Y')}", sub_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 14))
    total = sum(plan.values())
    elements.append(Paragraph(
        f"<b>Total Study Hours:</b> {total}h across {len(plan)} subjects", styles['Normal']))
    elements.append(Spacer(1, 12))
    data = [["#", "Subject", "Hours", "Study Tips"]]
    for i, (sub, hr) in enumerate(plan.items(), 1):
        tips = get_tips(sub)
        data.append([str(i), sub, f"{hr}h", " • ".join(tips[:2])])
    col_widths = [0.4*inch, 1.5*inch, 0.8*inch, 3.5*inch]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1, 0), colors.HexColor("#1a237e")),
        ('TEXTCOLOR',      (0, 0), (-1, 0), colors.white),
        ('FONTNAME',       (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1, 0), 11),
        ('ALIGN',          (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN',          (3, 1), (3, -1), 'LEFT'),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#e8eaf6"), colors.white]),
        ('GRID',           (0, 0), (-1, -1), 0.5, colors.HexColor("#9fa8da")),
        ('TOPPADDING',     (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 8),
        ('LEFTPADDING',    (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("<b>Detailed Tips Per Subject</b>", styles['Heading2']))
    elements.append(Spacer(1, 8))
    for sub in plan:
        elements.append(Paragraph(f"<b>{sub}</b>", styles['Heading3']))
        for tip in get_tips(sub):
            elements.append(Paragraph(f"- {tip}", tip_style))
        elements.append(Spacer(1, 6))
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Paragraph(
        "Generated by Smart Study Planner  |  Stay consistent, stay focused!",
        ParagraphStyle('Footer', parent=styles['Normal'],
                       fontSize=8, textColor=colors.grey, alignment=1)))
    doc.build(elements)
    return path

# ─────────────────────────────────────────
#  CHATBOT
# ─────────────────────────────────────────
CHATBOT_DATA = {
    "python":     ["Python ek powerful language hai. Daily practice karo.",
                   "Python mein projects banao — web, AI, automation sab possible hai."],
    "math":       ["Math mein daily 10 problems solve karo.",
                   "Concepts samjho, formulas baad mein yaad ho jaate hain."],
    "physics":    ["Physics mein diagrams banao aur real life se relate karo.",
                   "Numericals daily practice karo."],
    "chemistry":  ["Periodic table yaad karo step by step.",
                   "Equations balance karna practice karo."],
    "english":    ["Roz newspaper padho aur 5 naye words seekho.",
                   "Essay likhne ki practice karo."],
    "biology":    ["Diagrams banao aur body functions se relate karo.",
                   "Color coding se notes banao."],
    "history":    ["Timeline banao events ki.", "Story ki tarah padho — yaad rehta hai."],
    "study":      ["Consistency hi success ki chaabi hai.",
                   "Pomodoro try karo: 25 min study, 5 min break."],
    "exam":       ["Previous year papers zaroor solve karo.",
                   "Important topics revise karo aur notes banao."],
    "timetable":  ["AI timetable generator use karo — exam dates dalo, automatic schedule milega!",
                   "Timetable mein break day zaroor rakho — brain ko rest chahiye."],
    "time":       ["Time table banao aur usse follow karo.",
                   "Subah padhna zyada effective hota hai."],
    "motivation": ["Har din ek step aage badho.",
                   "Bade goals ko chhote tasks mein todo karo."],
    "stress":     ["Deep breathing karo. 5 min break lo.",
                   "Exercise aur neend zaroor lo — brain ke liye zaroori hai."],
    "notes":      ["Short notes banao, bullet points use karo.",
                   "Mind maps se concepts yaad rehte hain."],
    "timer":      ["Study timer use karo — 25 min focus, 5 min break.",
                   "Timer se concentration improve hoti hai!"],
    "pomodoro":   ["Pomodoro = 25 min study + 5 min break. 4 rounds ke baad 15 min break.",
                   "Pomodoro technique productivity ke liye best hai!"],
    "hello":      ["Hello! Kaise help kar sakta hoon?", "Hi! Study ke liye ready ho?"],
    "thanks":     ["Welcome! Mehnat karte raho!", "Koi baat nahi! All the best!"],
}

def chatbot_response(question):
    q = question.lower()
    for key, replies in CHATBOT_DATA.items():
        if key in q:
            return random.choice(replies)
    return "Mujhe abhi yeh topic nahi pata. Study, exam, timetable, ya kisi subject ke baare mein pucho!"

# ─────────────────────────────────────────
#  DB HELPERS
# ─────────────────────────────────────────
def get_last():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT name, subjects, hours FROM users ORDER BY id DESC LIMIT 1")
    data = cur.fetchone()
    conn.close()
    return data

def get_all_history():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT id, name, subjects, hours, created_at FROM users ORDER BY id DESC")
    data = cur.fetchall()
    conn.close()
    return data

# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def home():
    plan = None
    chat = None
    pdf  = None
    last = get_last()

    if request.method == "POST":

        if "generate" in request.form:
            name     = request.form.get("name", "").strip()
            subjects = request.form.get("subjects", "").strip()
            hours    = request.form.get("hours", "").strip()
            if not name or not subjects or not hours:
                flash("Please fill all fields!", "error")
            else:
                try:
                    h = int(hours)
                    if h <= 0:
                        flash("Hours must be greater than 0!", "error")
                    else:
                        subs = [s.strip() for s in subjects.split(",") if s.strip()]
                        priorities = {
                            s.lower(): request.form.get(
                                f"priority_{s.lower().replace(' ', '_')}", "medium")
                            for s in subs
                        }
                        plan = generate_plan(subjects, h, priorities)
                        pdf  = create_pdf(plan, name)
                        conn = sqlite3.connect(DB_PATH)
                        cur  = conn.cursor()
                        cur.execute(
                            "INSERT INTO users (name, subjects, hours, created_at) VALUES (?,?,?,?)",
                            (name, subjects, h, datetime.now().strftime("%d %b %Y %H:%M"))
                        )
                        conn.commit()
                        conn.close()
                        flash(f"Study plan generated for {name}!", "success")
                except ValueError:
                    flash("Please enter a valid number for hours!", "error")

        elif "ask" in request.form:
            q = request.form.get("question", "").strip()
            if q:
                chat = chatbot_response(q)
            else:
                flash("Please type a question!", "error")

        elif "log_streak" in request.form:
            sname  = request.form.get("streak_name", "").strip()
            shours = request.form.get("streak_hours", "").strip()
            if sname and shours:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur  = conn.cursor()
                    cur.execute(
                        "INSERT INTO streaks (name, date, hours_studied) VALUES (?,?,?)",
                        (sname, datetime.now().strftime("%Y-%m-%d"), float(shours))
                    )
                    conn.commit()
                    conn.close()
                    flash(f"Streak logged for {sname}!", "success")
                except Exception:
                    flash("Error logging streak.", "error")

    return render_template("index.html", plan=plan, chat=chat, last=last, pdf=pdf)


@app.route("/timetable", methods=["GET", "POST"])
def timetable():
    result = None

    if request.method == "POST":
        name        = request.form.get("tt_name", "").strip()
        subjects    = request.form.get("tt_subjects", "").strip()
        daily_hours = request.form.get("tt_hours", "6").strip()
        wake_time   = request.form.get("tt_wake", "6:00").strip()
        sleep_time  = request.form.get("tt_sleep", "22:00").strip()
        exam_dates  = request.form.get("tt_exams", "").strip()
        break_day   = request.form.get("tt_break", "Sunday").strip()
        goal        = request.form.get("tt_goal", "general").strip()

        if not subjects:
            flash("Please enter subjects!", "error")
        else:
            try:
                dh = int(daily_hours)
                result, err = ai_generate_timetable(
                    subjects, dh, wake_time, sleep_time,
                    exam_dates, break_day, goal
                )
                if err:
                    flash(err, "error")
                    result = None
                else:
                    conn = sqlite3.connect(DB_PATH)
                    cur  = conn.cursor()
                    cur.execute(
                        "INSERT INTO timetables (name, data, created_at) VALUES (?,?,?)",
                        (name or "Anonymous",
                         json.dumps({"subjects": subjects, "daily_hours": dh, "goal": goal}),
                         datetime.now().strftime("%d %b %Y %H:%M"))
                    )
                    conn.commit()
                    conn.close()
                    flash("AI Timetable generated!", "success")
            except ValueError:
                flash("Please enter a valid number for daily hours!", "error")

    return render_template("timetable.html", result=result)


@app.route("/history")
def history():
    return render_template("history.html", history=get_all_history())


@app.route("/delete/<int:uid>", methods=["POST"])
def delete_entry(uid):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    flash("Entry deleted.", "info")
    return redirect(url_for("history"))


if __name__ == "__main__":
    # Deployment fix: Bind to 0.0.0.0 and use PORT from environment
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
