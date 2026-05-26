import csv
import io
import os
import sqlite3
from math import ceil
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for, Response


app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-with-a-secure-secret-key"

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"
PER_PAGE = 8
ALLOWED_SORT_COLUMNS = {"id", "student_id", "name", "age", "course", "marks"}


def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db_connection()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            course TEXT NOT NULL,
            marks INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()


def get_grade(marks):
    if marks >= 85:
        return "A"
    if marks >= 70:
        return "B"
    if marks >= 50:
        return "C"
    return "F"


def validate_student_form(form):
    student_id = (form.get("student_id") or "").strip()
    name = (form.get("name") or "").strip()
    age_text = (form.get("age") or "").strip()
    course = (form.get("course") or "").strip()
    marks_text = (form.get("marks") or "").strip()

    errors = []

    if not student_id:
        errors.append("Student ID is required.")
    if not name:
        errors.append("Name is required.")
    if not age_text:
        errors.append("Age is required.")
    if not course:
        errors.append("Course is required.")
    if not marks_text:
        errors.append("Marks are required.")

    age = None
    marks = None

    if age_text:
        try:
            age = int(age_text)
            if age <= 0:
                errors.append("Age must be greater than 0.")
        except ValueError:
            errors.append("Age must be a valid number.")

    if marks_text:
        try:
            marks = int(marks_text)
            if marks < 0 or marks > 100:
                errors.append("Marks must be between 0 and 100.")
        except ValueError:
            errors.append("Marks must be a valid number.")

    data = {
        "student_id": student_id,
        "name": name,
        "age": age,
        "course": course,
        "marks": marks,
        "age_text": age_text,
        "marks_text": marks_text,
    }

    return data, errors


def build_search_clause(search_query, search_by):
    if search_query and search_by in {"name", "student_id"}:
        return f"WHERE {search_by} LIKE ?", [f"%{search_query}%"]
    return "", []


def validate_sort_params(sort_by, sort_dir):
    sort_by = sort_by if sort_by in ALLOWED_SORT_COLUMNS else "id"
    sort_dir = sort_dir.lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"
    return sort_by, sort_dir


def fetch_students(page=1, search_query="", search_by="name", sort_by="id", sort_dir="desc"):
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir)
    where_clause, params = build_search_clause(search_query, search_by)
    connection = get_db_connection()

    total = connection.execute(
        f"SELECT COUNT(*) FROM students {where_clause}", params
    ).fetchone()[0]

    offset = (page - 1) * PER_PAGE
    rows = connection.execute(
        f"""
        SELECT *
        FROM students
        {where_clause}
        ORDER BY {sort_by} {sort_dir}
        LIMIT ? OFFSET ?
        """,
        params + [PER_PAGE, offset],
    ).fetchall()
    connection.close()
    return rows, total


def fetch_all_students(search_query="", search_by="name", sort_by="id", sort_dir="desc"):
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir)
    where_clause, params = build_search_clause(search_query, search_by)
    connection = get_db_connection()
    rows = connection.execute(
        f"""
        SELECT *
        FROM students
        {where_clause}
        ORDER BY {sort_by} {sort_dir}
        """,
        params,
    ).fetchall()
    connection.close()
    return rows


def get_summary_statistics(search_query="", search_by="name"):
    where_clause, params = build_search_clause(search_query, search_by)
    connection = get_db_connection()
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            AVG(marks) AS avg_marks,
            SUM(CASE WHEN marks >= 85 THEN 1 ELSE 0 END) AS a_count,
            SUM(CASE WHEN marks >= 70 AND marks < 85 THEN 1 ELSE 0 END) AS b_count,
            SUM(CASE WHEN marks >= 50 AND marks < 70 THEN 1 ELSE 0 END) AS c_count,
            SUM(CASE WHEN marks < 50 THEN 1 ELSE 0 END) AS f_count
        FROM students
        {where_clause}
        """,
        params,
    ).fetchone()
    connection.close()

    return {
        "total": row["total"] or 0,
        "avg_marks": round(row["avg_marks"], 1) if row["avg_marks"] is not None else 0,
        "a_count": row["a_count"] or 0,
        "b_count": row["b_count"] or 0,
        "c_count": row["c_count"] or 0,
        "f_count": row["f_count"] or 0,
    }


@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    search_query = request.args.get("query", "").strip()
    search_by = request.args.get("search_by", "name").strip()
    sort_by = request.args.get("sort_by", "id").strip()
    sort_dir = request.args.get("sort_dir", "desc").strip()

    if search_by not in {"name", "student_id"}:
        search_by = "name"

    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir)

    students, total = fetch_students(
        page=page,
        search_query=search_query,
        search_by=search_by,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    student_list = []
    for student in students:
        student_dict = dict(student)
        student_dict["grade"] = get_grade(student_dict["marks"])
        student_list.append(student_dict)

    stats = get_summary_statistics(search_query, search_by)
    page_count = max(1, ceil(total / PER_PAGE))

    return render_template(
        "index.html",
        students=student_list,
        search_query=search_query,
        search_by=search_by,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_count=page_count,
        stats=stats,
        is_search=bool(search_query),
    )


@app.route("/search")
def search_student():
    query = request.args.get("query", "").strip()
    search_by = request.args.get("search_by", "name").strip()

    if not query:
        flash("Enter a name or Student ID to search.", "warning")
        return redirect(url_for("index"))

    if search_by not in {"name", "student_id"}:
        search_by = "name"

    return redirect(
        url_for(
            "index",
            query=query,
            search_by=search_by,
            page=1,
        )
    )


@app.route("/add", methods=["GET", "POST"])
def add_student():
    form_data = {
        "student_id": "",
        "name": "",
        "age_text": "",
        "course": "",
        "marks_text": "",
    }

    if request.method == "POST":
        data, errors = validate_student_form(request.form)
        form_data.update(data)

        connection = get_db_connection()
        duplicate = connection.execute(
            "SELECT id FROM students WHERE student_id = ?",
            (data["student_id"],),
        ).fetchone()

        if duplicate:
            errors.append("Student ID already exists. Use a unique Student ID.")

        if errors:
            connection.close()
            for error in errors:
                flash(error, "danger")
            return render_template("add_student.html", student=form_data)

        connection.execute(
            """
            INSERT INTO students (student_id, name, age, course, marks)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data["student_id"],
                data["name"],
                data["age"],
                data["course"],
                data["marks"],
            ),
        )
        connection.commit()
        connection.close()

        flash("Student added successfully.", "success")
        return redirect(url_for("index"))

    return render_template("add_student.html", student=form_data)


@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_student(id):
    connection = get_db_connection()
    student_row = connection.execute(
        "SELECT * FROM students WHERE id = ?",
        (id,),
    ).fetchone()

    if student_row is None:
        connection.close()
        flash("Student not found.", "warning")
        return redirect(url_for("index"))

    student = dict(student_row)
    student["age_text"] = str(student["age"])
    student["marks_text"] = str(student["marks"])

    if request.method == "POST":
        data, errors = validate_student_form(request.form)

        duplicate = connection.execute(
            "SELECT id FROM students WHERE student_id = ? AND id != ?",
            (data["student_id"], id),
        ).fetchone()
        if duplicate:
            errors.append("Student ID already exists. Use a unique Student ID.")

        if errors:
            connection.close()
            student.update(data)
            for error in errors:
                flash(error, "danger")
            return render_template("edit_student.html", student=student)

        connection.execute(
            """
            UPDATE students
            SET student_id = ?, name = ?, age = ?, course = ?, marks = ?
            WHERE id = ?
            """,
            (
                data["student_id"],
                data["name"],
                data["age"],
                data["course"],
                data["marks"],
                id,
            ),
        )
        connection.commit()
        connection.close()

        flash("Student updated successfully.", "success")
        return redirect(url_for("index"))

    connection.close()
    return render_template("edit_student.html", student=student)


@app.route("/delete/<int:id>", methods=["POST"])
def delete_student(id):
    connection = get_db_connection()
    student = connection.execute(
        "SELECT id FROM students WHERE id = ?",
        (id,),
    ).fetchone()

    if student is None:
        connection.close()
        flash("Student not found.", "warning")
        return redirect(url_for("index"))

    connection.execute("DELETE FROM students WHERE id = ?", (id,))
    connection.commit()
    connection.close()

    flash("Student deleted successfully.", "success")
    return redirect(url_for("index"))


@app.route("/export")
def export_students():
    search_query = request.args.get("query", "").strip()
    search_by = request.args.get("search_by", "name").strip()
    sort_by = request.args.get("sort_by", "id").strip()
    sort_dir = request.args.get("sort_dir", "desc").strip()

    students = fetch_all_students(
        search_query=search_query,
        search_by=search_by,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["student_id", "name", "age", "course", "marks"])
    for student in students:
        writer.writerow([
            student["student_id"],
            student["name"],
            student["age"],
            student["course"],
            student["marks"],
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=students.csv"
    return response


@app.route("/import", methods=["GET", "POST"])
def import_students():
    if request.method == "POST":
        csv_file = request.files.get("csv_file")
        if csv_file is None or csv_file.filename == "":
            flash("Please select a CSV file to upload.", "danger")
            return redirect(url_for("import_students"))

        try:
            content = csv_file.stream.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
        except Exception:
            flash("Unable to read the CSV file. Ensure it is valid UTF-8 CSV.", "danger")
            return redirect(url_for("import_students"))

        required_fields = {"student_id", "name", "age", "course", "marks"}
        if not required_fields.issubset(set(reader.fieldnames or [])):
            flash("CSV headers must include student_id, name, age, course, and marks.", "danger")
            return redirect(url_for("import_students"))

        imported = 0
        skipped = 0
        errors = []
        connection = get_db_connection()
        for row_number, row in enumerate(reader, start=1):
            data, row_errors = validate_student_form(row)
            if row_errors:
                skipped += 1
                errors.append(f"Row {row_number}: {', '.join(row_errors)}")
                continue

            duplicate = connection.execute(
                "SELECT id FROM students WHERE student_id = ?",
                (data["student_id"],),
            ).fetchone()
            if duplicate:
                skipped += 1
                errors.append(f"Row {row_number}: duplicate student_id {data['student_id']}")
                continue

            connection.execute(
                "INSERT INTO students (student_id, name, age, course, marks) VALUES (?, ?, ?, ?, ?)",
                (data["student_id"], data["name"], data["age"], data["course"], data["marks"]),
            )
            imported += 1

        connection.commit()
        connection.close()

        flash(f"Imported {imported} rows. Skipped {skipped} invalid or duplicate rows.", "success" if imported else "warning")
        if errors:
            for error in errors[:5]:
                flash(error, "danger")
            if len(errors) > 5:
                flash(f"...and {len(errors) - 5} more skipped rows.", "danger")

        return redirect(url_for("index"))

    return render_template("import_students.html")


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
