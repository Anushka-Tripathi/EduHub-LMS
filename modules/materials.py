"""Study material: professors upload files or add links; enrolled students download them."""
import mimetypes
import uuid
from pathlib import Path

import mysql.connector
from flask import (Blueprint, abort, flash, redirect, request, send_from_directory,
                   session, url_for)
from werkzeug.utils import secure_filename

import db
from config import Config
from modules.common import db_message, instructor_offering_or_403, role_required

bp = Blueprint("materials", __name__)

ALLOWED = {
    "pdf": "pdf", "ppt": "slides", "pptx": "slides", "doc": "other", "docx": "other",
    "xls": "other", "xlsx": "other", "csv": "other", "txt": "other", "md": "other",
    "zip": "other", "ipynb": "notebook", "py": "other", "sql": "other", "java": "other",
    "c": "other", "cpp": "other", "png": "other", "jpg": "other", "jpeg": "other",
    "mp4": "video", "webm": "video",
}
INLINE = {"pdf", "png", "jpg", "jpeg", "txt", "md", "mp4", "webm"}       # shown in the browser
MAGIC = {"pdf": (b"%PDF",), "png": (b"\x89PNG",), "jpg": (b"\xff\xd8",), "jpeg": (b"\xff\xd8",),
         "zip": (b"PK",), "docx": (b"PK",), "pptx": (b"PK",), "xlsx": (b"PK",)}


def material_dir(oid):
    path = Config.UPLOAD_DIR / "materials" / str(int(oid))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _my_module(oid, module_id):
    return db.query("SELECT module_id FROM module WHERE module_id = %s AND offering_id = %s",
                    (module_id, oid), one=True)


@bp.post("/instructor/offering/<int:oid>/modules")
@role_required("instructor", "admin")
def add_module(oid):
    instructor_offering_or_403(oid)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Give the module a title.", "error")
    else:
        try:
            db.execute("""INSERT INTO module (offering_id, module_number, title)
                          SELECT %s, COALESCE(MAX(module_number), 0) + 1, %s
                            FROM module WHERE offering_id = %s""", (oid, title[:150], oid))
            flash("Module added.", "success")
        except mysql.connector.Error as err:
            flash(db_message(err), "error")
    return redirect(url_for("instructor_offering", oid=oid) + "#materials")


@bp.post("/instructor/offering/<int:oid>/materials")
@role_required("instructor", "admin")
def upload_material(oid):
    instructor_offering_or_403(oid)
    f = request.form
    module = _my_module(oid, f.get("module_id", type=int))
    title = f.get("title", "").strip()
    link = f.get("resource_url", "").strip()
    upload = request.files.get("file")
    if not module or not title:
        flash("Choose a module and give the material a title.", "error")
        return redirect(url_for("instructor_offering", oid=oid) + "#materials")

    stored = original = mime = size = None
    mtype = f.get("material_type", "other")
    if upload and upload.filename:
        original = secure_filename(upload.filename)
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if ext not in ALLOWED:
            flash(f"Files of type .{ext or '?'} are not allowed. Allowed: " + ", ".join(sorted(ALLOWED)), "error")
            return redirect(url_for("instructor_offering", oid=oid) + "#materials")
        head = upload.stream.read(8)
        upload.stream.seek(0)
        if ext in MAGIC and not any(head.startswith(m) for m in MAGIC[ext]):
            flash("That file's content does not match its extension.", "error")
            return redirect(url_for("instructor_offering", oid=oid) + "#materials")
        stored = f"{uuid.uuid4().hex}.{ext}"
        path = material_dir(oid) / stored
        upload.save(path)
        size = path.stat().st_size
        mime = mimetypes.guess_type(original)[0] or "application/octet-stream"
        mtype = ALLOWED[ext]
        link = None
    elif link:
        if not link.lower().startswith(("http://", "https://")):
            flash("Links must start with http:// or https://", "error")
            return redirect(url_for("instructor_offering", oid=oid) + "#materials")
        if mtype not in ("video", "pdf", "slides", "notebook", "link", "other"):
            mtype = "link"
    else:
        flash("Attach a file or paste a link.", "error")
        return redirect(url_for("instructor_offering", oid=oid) + "#materials")

    uploader = session["user"]["instructor_id"] or db.query(
        "SELECT instructor_id FROM offering_instructor WHERE offering_id = %s ORDER BY role LIMIT 1",
        (oid,), one=True)["instructor_id"]
    try:
        mid = db.execute(
            """INSERT INTO material (module_id, title, description, material_type, resource_url,
                                     stored_name, original_name, file_size, mime_type, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (module["module_id"], title[:150], (f.get("description") or "")[:300] or None, mtype,
             link, stored, original, size, mime, uploader))
        db.log_event("UPLOAD", "material", mid, f"{original or link} ({size or 0} bytes)")
        flash("Material published to students.", "success")
    except mysql.connector.Error as err:
        if stored:
            (material_dir(oid) / stored).unlink(missing_ok=True)
        flash(db_message(err), "error")
    return redirect(url_for("instructor_offering", oid=oid) + "#materials")


def _material_for(mid):
    return db.query(
        """SELECT ma.*, mo.offering_id FROM material ma JOIN module mo ON mo.module_id = ma.module_id
            WHERE ma.material_id = %s""", (mid,), one=True)


@bp.post("/instructor/materials/<int:mid>/delete")
@role_required("instructor", "admin")
def delete_material(mid):
    m = _material_for(mid)
    if not m:
        abort(404)
    instructor_offering_or_403(m["offering_id"])
    db.execute("DELETE FROM material WHERE material_id = %s", (mid,))
    if m["stored_name"]:
        (material_dir(m["offering_id"]) / m["stored_name"]).unlink(missing_ok=True)
    db.log_event("DELETE", "material", mid, m["title"])
    flash("Material removed.", "success")
    return redirect(url_for("instructor_offering", oid=m["offering_id"]) + "#materials")


@bp.post("/instructor/materials/<int:mid>/toggle")
@role_required("instructor", "admin")
def toggle_material(mid):
    m = _material_for(mid)
    if not m:
        abort(404)
    instructor_offering_or_403(m["offering_id"])
    db.execute("UPDATE material SET is_published = NOT is_published WHERE material_id = %s", (mid,))
    return redirect(url_for("instructor_offering", oid=m["offering_id"]) + "#materials")


@bp.get("/materials/<int:mid>/download")
@role_required("student", "instructor", "admin")
def download(mid):
    m = _material_for(mid)
    if not m or not m["stored_name"]:
        abort(404)
    user = session["user"]
    if user["role"] == "student":
        ok = db.query("""SELECT 1 AS ok FROM enrollment WHERE student_id = %s AND offering_id = %s
                           AND status IN ('enrolled', 'completed', 'failed')""",
                      (user["student_id"], m["offering_id"]), one=True)
        if not ok or not m["is_published"]:
            abort(403)
    else:
        instructor_offering_or_403(m["offering_id"])
    ext = m["stored_name"].rsplit(".", 1)[-1]
    return send_from_directory(material_dir(m["offering_id"]), m["stored_name"],
                               as_attachment=ext not in INLINE or request.args.get("dl") == "1",
                               download_name=m["original_name"] or m["stored_name"])
