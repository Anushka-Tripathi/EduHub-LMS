#!/usr/bin/env python3
"""Draws the entity-relationship diagram from the live database (information_schema), so it cannot drift
from the real schema.   python scripts/make_er_diagram.py  ->  docs/img/er_diagram.png / .svg   (needs Graphviz `dot`)"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import db  # noqa: E402

GROUPS = {
    "People and accounts": ("#E8EEFF", ["department", "program", "student", "instructor", "user_account", "mentorship", "login_attempt"]),
    "Curriculum": ("#E6F6F0", ["course", "course_prerequisite", "program_course", "academic_term", "course_offering", "offering_instructor", "enrollment", "grade_scale", "course_result"]),
    "Teaching": ("#FFF4DE", ["module", "material", "class_session", "timetable_slot", "holiday", "notification", "notification_read"]),
    "Attendance": ("#FDE9E9", ["attendance", "qr_window", "attendance_scan_log"]),
    "Assessment": ("#F1E9FB", ["assignment", "submission", "quiz", "question", "question_option", "quiz_attempt", "quiz_answer", "course_feedback"]),
    "Services and audit": ("#E4F3F8", ["fee_invoice", "fee_payment", "service_request", "audit_log"]),
}


def build(selected, stem, rankdir="TB"):
    schema = db.CONFIG["database"]
    cols = db.query("""SELECT table_name AS t, column_name AS c, column_key AS k FROM information_schema.columns
                        WHERE table_schema = %s ORDER BY table_name, ordinal_position""", (schema,))
    fks = db.query("""SELECT table_name AS t, referenced_table_name AS r, column_name AS c FROM information_schema.key_column_usage
                       WHERE table_schema = %s AND referenced_table_name IS NOT NULL""", (schema,))
    fk_cols = {(f["t"], f["c"]) for f in fks}
    tables = {}
    for c in cols:
        tables.setdefault(c["t"], []).append(c)
    lines = ['digraph ER {', f'graph [rankdir={rankdir}, splines=true, nodesep=0.3, ranksep=0.9, compound=true, fontname="Helvetica", pad=0.3, newrank=true];',
             'node [shape=plain, fontname="Helvetica", fontsize=14];', 'edge [color="#7A86A8", arrowsize=0.7, penwidth=0.9];']
    placed = set()
    wanted = {t for g in selected for t in GROUPS[g][1]}
    for i, (title, (color, names)) in enumerate((g, GROUPS[g]) for g in selected):
        lines.append(f'subgraph cluster_{i} {{ label="{title}"; fontsize=18; fontcolor="#333B5C"; style="rounded,filled"; fillcolor="{color}60"; color="{color}";')
        for t in names:
            if t not in tables:
                continue
            placed.add(t)
            rows = []
            for c in tables[t]:
                is_pk, is_fk = c["k"] == "PRI", (t, c["c"]) in fk_cols
                if is_pk or is_fk:
                    tag = "PK" if is_pk and not is_fk else "PK,FK" if is_pk else "FK"
                    rows.append(f'<TR><TD ALIGN="LEFT" PORT="{c["c"]}"><FONT COLOR="{"#B4234A" if is_pk else "#2F6FDE"}">{tag}</FONT> {c["c"]}</TD></TR>')
            rows = rows or ['<TR><TD ALIGN="LEFT">&nbsp;</TD></TR>']
            lines.append(f'{t} [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3" BGCOLOR="white" COLOR="#5B6B9A">'
                         f'<TR><TD BGCOLOR="#3F4F8F"><FONT COLOR="white"><B>{t}</B></FONT></TD></TR>{"".join(rows)}</TABLE>>];')
        lines.append("}")
    stubs = {f["r"] for f in fks if f["t"] in wanted and f["r"] not in wanted}     # parents that live in another diagram
    for t in sorted(stubs):
        lines.append(f'{t} [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" BGCOLOR="#EEEEEE" COLOR="#9AA0B5"><TR><TD><I>{t}</I></TD></TR></TABLE>>];')
    views = {r["table_name"] for r in db.query("SELECT table_name AS table_name FROM information_schema.views WHERE table_schema = %s", (schema,))}
    for f in fks:
        if f["t"] in wanted and f["r"] in (wanted | stubs):
            lines.append(f'{f["t"]} -> {f["r"]};')
    lines.append("}")
    out = ROOT / "docs" / "img"
    out.mkdir(parents=True, exist_ok=True)
    dot = "\n".join(lines)
    (out / f"{stem}.dot").write_text(dot, encoding="utf-8")
    for fmt, extra in (("png", ["-Gdpi=130"]), ("svg", [])):
        subprocess.run(["dot", f"-T{fmt}", *extra, str(out / f"{stem}.dot"), "-o", str(out / f"{stem}.{fmt}")], check=True)
    print(f"{stem}: {len(wanted)} tables drawn ({len(stubs)} referenced stubs)")


def main():
    build(list(GROUPS), "er_diagram")
    build(["People and accounts", "Curriculum"], "er_part1_people_curriculum", "LR")
    build(["Teaching", "Attendance"], "er_part2_teaching_attendance", "LR")
    build(["Assessment", "Services and audit"], "er_part3_assessment_services", "LR")


if __name__ == "__main__":
    main()
