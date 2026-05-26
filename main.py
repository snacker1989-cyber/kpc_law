from __future__ import annotations

import html
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.db import (
    BASE_DIR,
    get_connection,
    get_or_create_department,
    init_db,
    list_options,
    log_action,
    replace_sections,
    sections_to_body,
)

app = FastAPI(title="사내규정 이력관리 시스템")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

UPLOAD_DIR = BASE_DIR / "uploads"


def fetch_home_regulations(conn):
    return conn.execute(
        """
        SELECT r.id, r.title, r.regulation_number, r.status,
               r.home_visible, r.home_sort_order,
               c.name AS category_name,
               d.name AS department_name,
               (
                   SELECT rv.effective_date
                   FROM regulation_versions rv
                   WHERE rv.regulation_id = r.id
                   ORDER BY rv.effective_date DESC, rv.id DESC
                   LIMIT 1
               ) AS effective_date,
               (
                   SELECT rv.amendment_type
                   FROM regulation_versions rv
                   WHERE rv.regulation_id = r.id
                   ORDER BY rv.effective_date DESC, rv.id DESC
                   LIMIT 1
               ) AS amendment_type
        FROM regulations r
        JOIN categories c ON c.id = r.category_id
        JOIN departments d ON d.id = r.department_id
        WHERE r.home_visible = 1
        ORDER BY r.home_sort_order, r.title
        """
    ).fetchall()


def form_sections(numbers: list[str], titles: list[str], contents: list[str]) -> list[dict[str, object]]:
    max_len = max(len(numbers), len(titles), len(contents), 0)
    sections = []
    for index in range(max_len):
        section = {
            "item_number": numbers[index] if index < len(numbers) else "",
            "title": titles[index] if index < len(titles) else "",
            "content": contents[index] if index < len(contents) else "",
            "amendment_note": "",
            "sort_order": index + 1,
        }
        if any(str(value).strip() for value in section.values()):
            sections.append(section)
    return sections


def form_sections_with_notes(
    numbers: list[str],
    titles: list[str],
    contents: list[str],
    notes: list[str],
) -> list[dict[str, object]]:
    sections = form_sections(numbers, titles, contents)
    for index, section in enumerate(sections):
        section["amendment_note"] = notes[index] if index < len(notes) else ""
    return sections


def render_section_content(section, links_by_section: dict[int, list]) -> Markup:
    rendered = html.escape(section["content"] or "")
    links = sorted(links_by_section.get(section["id"], []), key=lambda row: len(row["display_text"]), reverse=True)
    for link in links:
        text = str(link["display_text"] or "").strip()
        if not text:
            continue
        escaped_text = html.escape(text)
        if link["link_type"] == "external" and link["external_url"]:
            replacement = (
                f'<a class="law-ref external-ref" href="{html.escape(link["external_url"])}" '
                f'target="_blank" rel="noopener">{escaped_text}</a>'
            )
        else:
            replacement = (
                f'<button type="button" class="law-ref internal-ref" '
                f'data-link-id="{link["id"]}">{escaped_text}</button>'
            )
        rendered = rendered.replace(escaped_text, replacement)
    return Markup(rendered)


def fetch_section_options(conn):
    return conn.execute(
        """
        SELECT rs.id, rs.item_number, rs.title AS section_title,
               r.title AS regulation_title, rv.effective_date
        FROM regulation_sections rs
        JOIN regulation_versions rv ON rv.id = rs.regulation_version_id
        JOIN regulations r ON r.id = rv.regulation_id
        WHERE rv.id = (
            SELECT rv2.id
            FROM regulation_versions rv2
            WHERE rv2.regulation_id = r.id
            ORDER BY rv2.effective_date DESC, rv2.id DESC
            LIMIT 1
        )
        ORDER BY r.title, rs.sort_order, rs.id
        """
    ).fetchall()


@app.on_event("startup")
def startup() -> None:
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/")
def home(request: Request, q: str = ""):
    with get_connection() as conn:
        featured = fetch_home_regulations(conn)
    return templates.TemplateResponse("home.html", {"request": request, "q": q, "featured": featured})


@app.get("/regulations")
def regulations(request: Request, q: str = "", category_id: int | None = None):
    params: list[object] = []
    where = ["1 = 1"]
    if q:
        like = f"%{q}%"
        where.append(
            """
            (
                r.title LIKE ? OR r.regulation_number LIKE ? OR rv.body LIKE ?
                OR rv.reason LIKE ? OR rs.title LIKE ? OR rs.content LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like, like])
    if category_id:
        where.append("r.category_id = ?")
        params.append(category_id)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT r.id, r.title, r.regulation_number, r.status,
                   c.name AS category_name, d.name AS department_name,
                   (
                       SELECT effective_date
                       FROM regulation_versions
                       WHERE regulation_id = r.id
                       ORDER BY effective_date DESC, id DESC
                       LIMIT 1
                   ) AS latest_effective_date
            FROM regulations r
            JOIN categories c ON c.id = r.category_id
            JOIN departments d ON d.id = r.department_id
            LEFT JOIN regulation_versions rv ON rv.regulation_id = r.id
            LEFT JOIN regulation_sections rs ON rs.regulation_version_id = rv.id
            WHERE {" AND ".join(where)}
            ORDER BY r.title
            """,
            params,
        ).fetchall()
    context = {"request": request, "rows": rows, "q": q, **list_options(), "category_id": category_id}
    return templates.TemplateResponse("regulations.html", context)


@app.get("/regulations/{regulation_id}")
def regulation_detail(request: Request, regulation_id: int, tab: str = "body", version_id: int | None = None):
    with get_connection() as conn:
        regulation = conn.execute(
            """
            SELECT r.*, c.name AS category_name, d.name AS department_name
            FROM regulations r
            JOIN categories c ON c.id = r.category_id
            JOIN departments d ON d.id = r.department_id
            WHERE r.id = ?
            """,
            (regulation_id,),
        ).fetchone()
        if not regulation:
            raise HTTPException(status_code=404, detail="규정을 찾을 수 없습니다.")

        versions = conn.execute(
            "SELECT * FROM regulation_versions WHERE regulation_id = ? ORDER BY effective_date DESC, id DESC",
            (regulation_id,),
        ).fetchall()
        if not versions:
            raise HTTPException(status_code=404, detail="등록된 버전이 없습니다.")

        version = None
        if version_id:
            version = conn.execute(
                "SELECT * FROM regulation_versions WHERE id = ? AND regulation_id = ?",
                (version_id, regulation_id),
            ).fetchone()
        version = version or versions[0]

        sections = conn.execute(
            """
            SELECT * FROM regulation_sections
            WHERE regulation_version_id = ?
            ORDER BY sort_order, id
            """,
            (version["id"],),
        ).fetchall()
        links = conn.execute(
            """
            SELECT * FROM section_links
            WHERE source_section_id IN (
                SELECT id FROM regulation_sections WHERE regulation_version_id = ?
            )
            ORDER BY id
            """,
            (version["id"],),
        ).fetchall()
        attachments = conn.execute(
            "SELECT * FROM attachments WHERE regulation_version_id = ? ORDER BY sort_order, id",
            (version["id"],),
        ).fetchall()
        sidebar_regulations = fetch_home_regulations(conn)
        links_by_section: dict[int, list] = {}
        for link in links:
            links_by_section.setdefault(int(link["source_section_id"]), []).append(link)
        rendered_sections = [
            {"row": section, "content_html": render_section_content(section, links_by_section)}
            for section in sections
        ]

    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "regulation": regulation,
            "versions": versions,
            "version": version,
            "sections": sections,
            "rendered_sections": rendered_sections,
            "attachments": attachments,
            "sidebar_regulations": sidebar_regulations,
            "tab": tab,
        },
    )


@app.get("/section-links/{link_id}/preview")
def section_link_preview(request: Request, link_id: int):
    with get_connection() as conn:
        link = conn.execute("SELECT * FROM section_links WHERE id = ?", (link_id,)).fetchone()
        if not link or link["link_type"] != "internal" or not link["target_section_id"]:
            raise HTTPException(status_code=404, detail="연결된 조문을 찾을 수 없습니다.")
        target = conn.execute(
            """
            SELECT rs.*, rv.effective_date, r.title AS regulation_title
            FROM regulation_sections rs
            JOIN regulation_versions rv ON rv.id = rs.regulation_version_id
            JOIN regulations r ON r.id = rv.regulation_id
            WHERE rs.id = ?
            """,
            (link["target_section_id"],),
        ).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="연결된 조문을 찾을 수 없습니다.")
    return templates.TemplateResponse("section_preview.html", {"request": request, "target": target})


@app.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int):
    with get_connection() as conn:
        attachment = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not attachment:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다.")
    path = BASE_DIR / attachment["file_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="파일이 존재하지 않습니다.")
    return FileResponse(path, filename=attachment["file_name"])


@app.get("/admin/regulations")
def admin_regulations(request: Request):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*, c.name AS category_name, d.name AS department_name
            FROM regulations r
            JOIN categories c ON c.id = r.category_id
            JOIN departments d ON d.id = r.department_id
            ORDER BY r.updated_at DESC, r.id DESC
            """
        ).fetchall()
    return templates.TemplateResponse("admin_regulations.html", {"request": request, "rows": rows})


@app.post("/admin/regulations/home-order")
async def update_home_order(request: Request):
    form = await request.form()
    visible_ids = {int(value) for value in form.getlist("visible_ids")}
    with get_connection() as conn:
        rows = conn.execute("SELECT id, title FROM regulations").fetchall()
        for row in rows:
            sort_value = form.get(f"sort_order_{row['id']}", "100")
            try:
                sort_order = int(str(sort_value))
            except ValueError:
                sort_order = 100
            conn.execute(
                """
                UPDATE regulations
                SET home_visible = ?, home_sort_order = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (1 if row["id"] in visible_ids else 0, sort_order, row["id"]),
            )
        log_action(conn, "update", "regulation", 0, "홈 노출 순서 수정")
    return RedirectResponse("/admin/regulations", status_code=303)


@app.get("/admin/links")
def admin_links(request: Request):
    with get_connection() as conn:
        links = conn.execute(
            """
            SELECT sl.*, src.item_number AS source_number, src.title AS source_title,
                   sr.title AS source_regulation,
                   tgt.item_number AS target_number, tgt.title AS target_title,
                   tr.title AS target_regulation
            FROM section_links sl
            JOIN regulation_sections src ON src.id = sl.source_section_id
            JOIN regulation_versions sv ON sv.id = src.regulation_version_id
            JOIN regulations sr ON sr.id = sv.regulation_id
            LEFT JOIN regulation_sections tgt ON tgt.id = sl.target_section_id
            LEFT JOIN regulation_versions tv ON tv.id = tgt.regulation_version_id
            LEFT JOIN regulations tr ON tr.id = tv.regulation_id
            ORDER BY sl.id DESC
            """
        ).fetchall()
        section_options = fetch_section_options(conn)
    return templates.TemplateResponse(
        "admin_links.html",
        {"request": request, "links": links, "section_options": section_options},
    )


@app.post("/admin/links")
def create_section_link(
    source_section_id: int = Form(...),
    display_text: str = Form(...),
    link_type: str = Form(...),
    target_section_id: str = Form(""),
    external_url: str = Form(""),
    memo: str = Form(""),
):
    target_id = int(target_section_id) if target_section_id.strip() else None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO section_links
                (source_section_id, display_text, link_type, target_section_id, external_url, memo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_section_id,
                display_text.strip(),
                link_type,
                target_id if link_type == "internal" else None,
                external_url.strip() if link_type == "external" else None,
                memo.strip(),
            ),
        )
        log_action(conn, "create", "section_link", source_section_id, f"관계 링크 등록: {display_text}")
    return RedirectResponse("/admin/links", status_code=303)


@app.post("/admin/links/{link_id}/delete")
def delete_section_link(link_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM section_links WHERE id = ?", (link_id,))
        log_action(conn, "delete", "section_link", link_id, "관계 링크 삭제")
    return RedirectResponse("/admin/links", status_code=303)


@app.get("/admin/regulations/new")
def new_regulation(request: Request):
    return templates.TemplateResponse("admin_regulation_form.html", {"request": request, **list_options()})


@app.post("/admin/regulations")
def create_regulation(
    title: str = Form(...),
    category_id: int = Form(...),
    department_name: str = Form(...),
    regulation_number: str = Form(""),
    version_label: str = Form("제정"),
    promulgation_date: str = Form(""),
    effective_date: str = Form(...),
    amendment_type: str = Form("제정"),
    reason: str = Form(""),
    section_numbers: list[str] = Form([]),
    section_titles: list[str] = Form([]),
    section_contents: list[str] = Form([]),
    section_notes: list[str] = Form([]),
):
    sections = form_sections_with_notes(section_numbers, section_titles, section_contents, section_notes)
    body = sections_to_body(sections)
    with get_connection() as conn:
        department_id = get_or_create_department(conn, department_name)
        cursor = conn.execute(
            """
            INSERT INTO regulations (title, category_id, department_id, regulation_number)
            VALUES (?, ?, ?, ?)
            """,
            (title.strip(), category_id, department_id, regulation_number.strip()),
        )
        regulation_id = cursor.lastrowid
        cursor = conn.execute(
            """
            INSERT INTO regulation_versions
                (regulation_id, version_label, promulgation_date, effective_date, amendment_type, reason, body)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (regulation_id, version_label.strip(), promulgation_date or None, effective_date, amendment_type, reason, body),
        )
        version_id = cursor.lastrowid
        replace_sections(conn, version_id, sections)
        log_action(conn, "create", "regulation", regulation_id, f"{title} 등록")
    return RedirectResponse(f"/regulations/{regulation_id}", status_code=303)


@app.get("/admin/regulations/{regulation_id}/edit")
def edit_regulation(request: Request, regulation_id: int):
    with get_connection() as conn:
        regulation = conn.execute(
            """
            SELECT r.*, c.name AS category_name, d.name AS department_name
            FROM regulations r
            JOIN categories c ON c.id = r.category_id
            JOIN departments d ON d.id = r.department_id
            WHERE r.id = ?
            """,
            (regulation_id,),
        ).fetchone()
        if not regulation:
            raise HTTPException(status_code=404, detail="규정을 찾을 수 없습니다.")
        version = conn.execute(
            """
            SELECT * FROM regulation_versions
            WHERE regulation_id = ?
            ORDER BY effective_date DESC, id DESC
            LIMIT 1
            """,
            (regulation_id,),
        ).fetchone()
        sections = conn.execute(
            "SELECT * FROM regulation_sections WHERE regulation_version_id = ? ORDER BY sort_order, id",
            (version["id"],),
        ).fetchall()
    return templates.TemplateResponse(
        "admin_edit_form.html",
        {
            "request": request,
            "regulation": regulation,
            "version": version,
            "sections": sections,
            **list_options(),
        },
    )


@app.post("/admin/regulations/{regulation_id}/edit")
def update_regulation(
    regulation_id: int,
    title: str = Form(...),
    category_id: int = Form(...),
    department_name: str = Form(...),
    regulation_number: str = Form(""),
    version_label: str = Form(...),
    promulgation_date: str = Form(""),
    effective_date: str = Form(...),
    amendment_type: str = Form(...),
    reason: str = Form(""),
    section_numbers: list[str] = Form([]),
    section_titles: list[str] = Form([]),
    section_contents: list[str] = Form([]),
    section_notes: list[str] = Form([]),
):
    sections = form_sections_with_notes(section_numbers, section_titles, section_contents, section_notes)
    body = sections_to_body(sections)
    with get_connection() as conn:
        regulation = conn.execute("SELECT * FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
        if not regulation:
            raise HTTPException(status_code=404, detail="규정을 찾을 수 없습니다.")
        version = conn.execute(
            """
            SELECT * FROM regulation_versions
            WHERE regulation_id = ?
            ORDER BY effective_date DESC, id DESC
            LIMIT 1
            """,
            (regulation_id,),
        ).fetchone()
        department_id = get_or_create_department(conn, department_name)
        conn.execute(
            """
            UPDATE regulations
            SET title = ?, category_id = ?, department_id = ?, regulation_number = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title.strip(), category_id, department_id, regulation_number.strip(), regulation_id),
        )
        conn.execute(
            """
            UPDATE regulation_versions
            SET version_label = ?, promulgation_date = ?, effective_date = ?,
                amendment_type = ?, reason = ?, body = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (version_label.strip(), promulgation_date or None, effective_date, amendment_type, reason, body, version["id"]),
        )
        replace_sections(conn, version["id"], sections)
        log_action(conn, "update", "regulation", regulation_id, f"{title} 현재 상태 편집")
    return RedirectResponse(f"/regulations/{regulation_id}", status_code=303)


@app.get("/admin/regulations/{regulation_id}/versions/new")
def new_version(request: Request, regulation_id: int):
    with get_connection() as conn:
        regulation = conn.execute("SELECT * FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
    if not regulation:
        raise HTTPException(status_code=404, detail="규정을 찾을 수 없습니다.")
    return templates.TemplateResponse("admin_version_form.html", {"request": request, "regulation": regulation})


@app.post("/admin/regulations/{regulation_id}/versions")
def create_version(
    regulation_id: int,
    version_label: str = Form(...),
    promulgation_date: str = Form(""),
    effective_date: str = Form(...),
    amendment_type: str = Form(...),
    reason: str = Form(""),
    section_numbers: list[str] = Form([]),
    section_titles: list[str] = Form([]),
    section_contents: list[str] = Form([]),
    section_notes: list[str] = Form([]),
    attachment_title: str = Form(""),
    attachment_file: UploadFile | None = File(None),
):
    sections = form_sections_with_notes(section_numbers, section_titles, section_contents, section_notes)
    body = sections_to_body(sections)
    with get_connection() as conn:
        regulation = conn.execute("SELECT * FROM regulations WHERE id = ?", (regulation_id,)).fetchone()
        if not regulation:
            raise HTTPException(status_code=404, detail="규정을 찾을 수 없습니다.")
        cursor = conn.execute(
            """
            INSERT INTO regulation_versions
                (regulation_id, version_label, promulgation_date, effective_date, amendment_type, reason, body)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (regulation_id, version_label.strip(), promulgation_date or None, effective_date, amendment_type, reason, body),
        )
        version_id = cursor.lastrowid
        replace_sections(conn, version_id, sections)

        if attachment_file and attachment_file.filename:
            safe_name = Path(attachment_file.filename).name
            stored_name = f"{uuid4().hex}_{safe_name}"
            stored_path = UPLOAD_DIR / stored_name
            with stored_path.open("wb") as out_file:
                shutil.copyfileobj(attachment_file.file, out_file)
            conn.execute(
                """
                INSERT INTO attachments
                    (regulation_version_id, title, file_name, file_path, file_type, file_size)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    attachment_title.strip() or safe_name,
                    safe_name,
                    str(stored_path.relative_to(BASE_DIR)),
                    attachment_file.content_type,
                    stored_path.stat().st_size,
                ),
            )

        log_action(conn, "create", "version", version_id, f"{regulation['title']} 버전 추가")
    return RedirectResponse(f"/regulations/{regulation_id}?version_id={version_id}", status_code=303)
