from __future__ import annotations

import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "regulations.sqlite3"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS regulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category_id INTEGER NOT NULL REFERENCES categories(id),
                department_id INTEGER NOT NULL REFERENCES departments(id),
                regulation_number TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                home_visible INTEGER NOT NULL DEFAULT 1,
                home_sort_order INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS regulation_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regulation_id INTEGER NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
                version_label TEXT NOT NULL,
                promulgation_date TEXT,
                effective_date TEXT NOT NULL,
                amendment_type TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS regulation_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regulation_version_id INTEGER NOT NULL REFERENCES regulation_versions(id) ON DELETE CASCADE,
                item_number TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                amendment_note TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS section_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_section_id INTEGER NOT NULL REFERENCES regulation_sections(id) ON DELETE CASCADE,
                display_text TEXT NOT NULL,
                link_type TEXT NOT NULL DEFAULT 'internal',
                target_section_id INTEGER REFERENCES regulation_sections(id) ON DELETE SET NULL,
                external_url TEXT,
                memo TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regulation_version_id INTEGER NOT NULL REFERENCES regulation_versions(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        ensure_columns(conn)
        seed_if_empty(conn)
        backfill_sections(conn)


def ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(regulations)").fetchall()}
    if "home_visible" not in columns:
        conn.execute("ALTER TABLE regulations ADD COLUMN home_visible INTEGER NOT NULL DEFAULT 1")
    if "home_sort_order" not in columns:
        conn.execute("ALTER TABLE regulations ADD COLUMN home_sort_order INTEGER NOT NULL DEFAULT 100")
    section_columns = {row["name"] for row in conn.execute("PRAGMA table_info(regulation_sections)").fetchall()}
    if "amendment_note" not in section_columns:
        conn.execute("ALTER TABLE regulation_sections ADD COLUMN amendment_note TEXT NOT NULL DEFAULT ''")


def seed_if_empty(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) FROM regulations").fetchone()[0]
    if count:
        return

    conn.executemany(
        "INSERT INTO categories (name, sort_order) VALUES (?, ?)",
        [("인사", 1), ("복무", 2), ("재무", 3), ("보안", 4)],
    )
    conn.executemany(
        "INSERT INTO departments (name, sort_order) VALUES (?, ?)",
        [("인사팀", 1), ("경영지원팀", 2), ("정보보안팀", 3)],
    )
    cursor = conn.execute(
        """
        INSERT INTO regulations
            (title, category_id, department_id, regulation_number, status, home_visible, home_sort_order)
        VALUES
            ('취업규칙', 1, 1, '인사-001', 'active', 1, 1)
        """
    )
    regulation_id = cursor.lastrowid
    conn.executemany(
        """
        INSERT INTO regulation_versions
            (regulation_id, version_label, promulgation_date, effective_date, amendment_type, reason, body)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                regulation_id,
                "제정",
                "2024-01-01",
                "2024-01-01",
                "제정",
                "회사 운영 기준과 임직원의 기본 복무 원칙을 명확히 하기 위해 제정합니다.",
                "제1조(목적)\n이 규칙은 임직원의 근로조건과 복무질서를 정함을 목적으로 한다.\n\n제2조(적용범위)\n이 규칙은 회사의 모든 임직원에게 적용한다.",
            ),
            (
                regulation_id,
                "일부개정 2025.03.01",
                "2025-02-15",
                "2025-03-01",
                "일부개정",
                "유연근무제 운영 기준을 보완하고 휴가 신청 절차를 간소화합니다.",
                "제1조(목적)\n이 규칙은 임직원의 근로조건과 복무질서를 정함을 목적으로 한다.\n\n제2조(적용범위)\n이 규칙은 회사의 모든 임직원에게 적용한다.\n\n제3조(유연근무)\n회사는 업무상 필요와 근로자의 신청을 고려하여 유연근무를 승인할 수 있다.",
            ),
        ],
    )


def list_options() -> dict[str, list[sqlite3.Row]]:
    with get_connection() as conn:
        return {
            "categories": conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall(),
            "departments": conn.execute("SELECT * FROM departments ORDER BY sort_order, name").fetchall(),
        }


def get_or_create_department(conn: sqlite3.Connection, name: str) -> int:
    department_name = name.strip() or "미지정"
    row = conn.execute("SELECT id FROM departments WHERE name = ?", (department_name,)).fetchone()
    if row:
        return int(row["id"])
    cursor = conn.execute(
        "INSERT INTO departments (name, sort_order) VALUES (?, ?)",
        (department_name, 100),
    )
    return int(cursor.lastrowid)


def parse_sections(body: str) -> list[dict[str, object]]:
    pattern = re.compile(r"^\s*(제\d+조(?:의\d+)?)\s*\(([^)]+)\)", re.MULTILINE)
    matches = list(pattern.finditer(body or ""))
    if not matches:
        return []

    sections: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        sections.append(
            {
                "item_number": match.group(1),
                "title": match.group(2).strip(),
                "content": content,
                "amendment_note": "",
                "sort_order": index + 1,
            }
        )
    return sections


def sections_to_body(sections: list[dict[str, object]]) -> str:
    chunks = []
    for section in sections:
        number = str(section.get("item_number") or "").strip()
        title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "").strip()
        note = str(section.get("amendment_note") or "").strip()
        if not number and not title and not content:
            continue
        heading = f"{number}({title})" if number and title else f"{number}{title}"
        if note:
            heading = f"{heading} {note}"
        chunks.append(f"{heading}\n{content}".strip())
    return "\n\n".join(chunks)


def replace_sections(conn: sqlite3.Connection, version_id: int, sections: list[dict[str, object]]) -> None:
    conn.execute("DELETE FROM regulation_sections WHERE regulation_version_id = ?", (version_id,))
    for index, section in enumerate(sections, start=1):
        number = str(section.get("item_number") or "").strip()
        title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "").strip()
        note = str(section.get("amendment_note") or "").strip()
        if not number and not title and not content:
            continue
        conn.execute(
            """
            INSERT INTO regulation_sections
                (regulation_version_id, item_number, title, content, amendment_note, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (version_id, number or f"제{index}조", title or "제목 없음", content, note, index),
        )


def backfill_sections(conn: sqlite3.Connection) -> None:
    versions = conn.execute("SELECT id, body FROM regulation_versions").fetchall()
    for version in versions:
        count = conn.execute(
            "SELECT COUNT(*) FROM regulation_sections WHERE regulation_version_id = ?",
            (version["id"],),
        ).fetchone()[0]
        if count:
            continue
        sections = parse_sections(version["body"])
        if sections:
            replace_sections(conn, int(version["id"]), sections)


def log_action(conn: sqlite3.Connection, action: str, target_type: str, target_id: int, summary: str) -> None:
    conn.execute(
        "INSERT INTO audit_logs (action, target_type, target_id, summary) VALUES (?, ?, ?, ?)",
        (action, target_type, target_id, summary),
    )
