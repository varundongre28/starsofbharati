from flask import Flask, request, jsonify, send_from_directory, Response
import sqlite3, json, csv, io, os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "votes.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
PHOTOS_DIR = os.path.join(STATIC_DIR, "photos")
ADMIN_PIN = "Bharat2026"

app = Flask(__name__, static_folder="static", static_url_path="")

def connect_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect_db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            voter_id INTEGER NOT NULL,
            voter_name TEXT NOT NULL,
            choices TEXT NOT NULL,
            remarks TEXT NOT NULL,
            disqualified INTEGER DEFAULT 0
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS admin_choices (
            award_key TEXT PRIMARY KEY,
            member_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS trivia_scores (
            voter_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            right_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            accuracy INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """)
        con.commit()

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/photos/")
def list_photos():
    if not os.path.isdir(PHOTOS_DIR):
        return jsonify([])
    files = [
        f for f in os.listdir(PHOTOS_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(PHOTOS_DIR, f)), reverse=True)
    # Return a simple HTML directory listing, because the HTML parser also supports href scanning.
    html = "<html><body>" + "".join(f'<a href="{f}">{f}</a><br>' for f in files) + "</body></html>"
    return html

@app.route("/photos/<path:filename>")
def photos(filename):
    return send_from_directory(PHOTOS_DIR, filename, max_age=3600)

@app.route("/api/votes", methods=["GET"])
def api_votes():
    with connect_db() as con:
        rows = con.execute("SELECT * FROM votes ORDER BY id ASC").fetchall()
    votes = []
    for r in rows:
        votes.append({
            "id": r["id"],
            "time": r["timestamp"],
            "voterId": r["voter_id"],
            "voterName": r["voter_name"],
            "choices": json.loads(r["choices"]),
            "remarks": json.loads(r["remarks"]),
            "disqualified": bool(r["disqualified"])
        })
    return jsonify(votes)

@app.route("/api/submit-vote", methods=["POST"])
def submit_vote():
    data = request.get_json(force=True)
    voter_id = int(data.get("voterId"))
    voter_name = data.get("voterName", "")
    choices = data.get("choices", {})
    remarks = data.get("remarks", {})
    timestamp = data.get("time") or datetime.now().isoformat(timespec="seconds")

    with connect_db() as con:
        con.execute(
            "INSERT INTO votes(timestamp, voter_id, voter_name, choices, remarks, disqualified) VALUES(?,?,?,?,?,0)",
            (timestamp, voter_id, voter_name, json.dumps(choices, ensure_ascii=False), json.dumps(remarks, ensure_ascii=False))
        )
        con.commit()
        new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"ok": True, "id": new_id})

@app.route("/api/disqualify", methods=["POST"])
def disqualify_vote():
    data = request.get_json(force=True)
    if data.get("adminPin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "Wrong admin PIN"}), 403
    vote_id = int(data.get("voteId"))
    disqualified = 1 if data.get("disqualified") else 0
    with connect_db() as con:
        con.execute("UPDATE votes SET disqualified=? WHERE id=?", (disqualified, vote_id))
        con.commit()
    return jsonify({"ok": True})

@app.route("/api/admin-choices", methods=["GET"])
def get_admin_choices():
    with connect_db() as con:
        rows = con.execute("SELECT award_key, member_id FROM admin_choices").fetchall()
    return jsonify({r["award_key"]: r["member_id"] for r in rows})

@app.route("/api/admin-choice", methods=["POST"])
def set_admin_choice():
    data = request.get_json(force=True)
    if data.get("adminPin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "Wrong admin PIN"}), 403
    award_key = data.get("awardKey")
    member_id = int(data.get("memberId"))
    with connect_db() as con:
        con.execute("""
        INSERT INTO admin_choices(award_key, member_id, updated_at)
        VALUES(?,?,?)
        ON CONFLICT(award_key) DO UPDATE SET
            member_id=excluded.member_id,
            updated_at=excluded.updated_at
        """, (award_key, member_id, datetime.now().isoformat(timespec="seconds")))
        con.commit()
    return jsonify({"ok": True})

@app.route("/api/trivia-score", methods=["POST"])
@app.route("/api/trivia", methods=["POST"])
def trivia_score():
    data = request.get_json(force=True)
    voter_id = int(data.get("voterId") or data.get("voter_id") or 0)
    name = data.get("name") or data.get("voter") or ""
    right = int(data.get("right") or data.get("right_count") or 0)
    wrong = int(data.get("wrong") or data.get("wrong_count") or 0)
    total = right + wrong
    accuracy = round((right / total) * 100) if total else 0

    with connect_db() as con:
        con.execute("""
        INSERT INTO trivia_scores(voter_id, name, right_count, wrong_count, accuracy, updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(voter_id) DO UPDATE SET
            name=excluded.name,
            right_count=excluded.right_count,
            wrong_count=excluded.wrong_count,
            accuracy=excluded.accuracy,
            updated_at=excluded.updated_at
        """, (voter_id, name, right, wrong, accuracy, datetime.now().isoformat(timespec="seconds")))
        con.commit()
    return jsonify({"ok": True})

@app.route("/api/trivia-leaderboard", methods=["GET"])
@app.route("/api/trivia-board", methods=["GET"])
def trivia_leaderboard():
    with connect_db() as con:
        rows = con.execute("""
        SELECT voter_id, name, right_count, wrong_count, accuracy, updated_at
        FROM trivia_scores
        ORDER BY right_count DESC, wrong_count ASC, accuracy DESC
        LIMIT 10
        """).fetchall()
    return jsonify([{
        "voterId": r["voter_id"],
        "name": r["name"],
        "right": r["right_count"],
        "wrong": r["wrong_count"],
        "accuracy": r["accuracy"],
        "time": r["updated_at"]
    } for r in rows])

@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    with connect_db() as con:
        rows = con.execute("SELECT * FROM votes ORDER BY id ASC").fetchall()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Timestamp", "Voter Name", "Aurora Winner", "Iron Winner", "Sentinel Winner", "Remarks", "Validity"])

    for r in rows:
        choices = json.loads(r["choices"])
        remarks = json.loads(r["remarks"])
        writer.writerow([
            r["timestamp"],
            r["voter_name"],
            choices.get("aurora", ""),
            choices.get("pillar", ""),
            choices.get("sentinel", ""),
            "Aurora: {} | Iron: {} | Sentinel: {}".format(
                remarks.get("aurora", ""),
                remarks.get("pillar", ""),
                remarks.get("sentinel", "")
            ),
            "Disqualified" if r["disqualified"] else "Valid"
        ])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bharati_awards_votes.csv"}
    )

@app.route("/api/clear-local-note", methods=["GET"])
def note():
    return jsonify({"note": "Clear server votes manually by deleting votes.db after stopping Flask."})

@app.route("/api/clear-votes", methods=["POST"])
def clear_votes():
    data = request.get_json(force=True)
    if data.get("adminPin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "Wrong admin PIN"}), 403
    with connect_db() as con:
        con.execute("DELETE FROM votes")
        con.commit()
    return jsonify({"ok": True})

@app.route("/api/clear-trivia", methods=["POST"])
def clear_trivia():
    data = request.get_json(force=True)
    if data.get("adminPin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "Wrong admin PIN"}), 403
    with connect_db() as con:
        con.execute("DELETE FROM trivia_scores")
        con.commit()
    return jsonify({"ok": True})

@app.route("/api/reset-all", methods=["POST"])
def reset_all():
    data = request.get_json(force=True)
    if data.get("adminPin") != ADMIN_PIN:
        return jsonify({"ok": False, "error": "Wrong admin PIN"}), 403
    with connect_db() as con:
        con.execute("DELETE FROM votes")
        con.execute("DELETE FROM trivia_scores")
        con.execute("DELETE FROM admin_choices")
        con.commit()
    return jsonify({"ok": True})

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"Stars of Bharati running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
