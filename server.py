"""AI VIDEO PRODUCTION MCP — remote Streamable HTTP server.

Stores projects, prompts, characters, voice profiles and continuity notes in SQLite.
Protect the endpoint with MCP_API_KEY before deploying publicly.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP

APP_NAME = "ai-video-production"
DB_PATH = Path(os.getenv("DATABASE_PATH", "./data/video_production.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
API_KEY = os.getenv("MCP_API_KEY", "")

mcp = FastMCP(APP_NAME, stateless_http=True, json_response=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with closing(connect()) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT DEFAULT '',
            status TEXT DEFAULT 'planning',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS continuity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            part_number INTEGER NOT NULL,
            final_frame_description TEXT NOT NULL,
            next_part_start TEXT DEFAULT '',
            reference_notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """)
        db.commit()


@mcp.tool()
def create_project(title: str, topic: str = "", notes: str = "") -> dict[str, Any]:
    """Create a video project and return its project ID."""
    if not title.strip():
        raise ValueError("title bo'sh bo'lmasligi kerak")
    stamp = now()
    with closing(connect()) as db:
        cur = db.execute(
            "INSERT INTO projects(title,topic,notes,created_at,updated_at) VALUES(?,?,?,?,?)",
            (title.strip(), topic, notes, stamp, stamp),
        )
        db.commit()
        return {"project_id": cur.lastrowid, "title": title.strip(), "status": "planning"}


@mcp.tool()
def list_projects(status: str = "") -> list[dict[str, Any]]:
    """List saved video projects; optionally filter by status."""
    with closing(connect()) as db:
        if status:
            rows = db.execute("SELECT * FROM projects WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


@mcp.tool()
def update_project(project_id: int, title: str = "", topic: str = "", status: str = "", notes: str = "") -> dict[str, Any]:
    """Update supplied project fields. Valid statuses: planning, production, editing, complete, paused."""
    allowed = {"planning", "production", "editing", "complete", "paused"}
    if status and status not in allowed:
        raise ValueError(f"status quyidagilardan biri bo'lishi kerak: {', '.join(sorted(allowed))}")
    fields, values = [], []
    for key, value in (("title", title), ("topic", topic), ("status", status), ("notes", notes)):
        if value != "":
            fields.append(f"{key}=?")
            values.append(value)
    if not fields:
        raise ValueError("Kamida bitta maydonni yangilang")
    fields.append("updated_at=?")
    values.extend([now(), project_id])
    with closing(connect()) as db:
        cur = db.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id=?", values)
        db.commit()
        if not cur.rowcount:
            raise ValueError("Bunday project_id topilmadi")
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row)


@mcp.tool()
def save_asset(kind: str, name: str, content: str, project_id: int = 0, metadata_json: str = "{}") -> dict[str, Any]:
    """Save an asset. kind must be prompt, scenario, character, voice_profile, or reference."""
    allowed = {"prompt", "scenario", "character", "voice_profile", "reference"}
    if kind not in allowed:
        raise ValueError(f"kind quyidagilardan biri bo'lishi kerak: {', '.join(sorted(allowed))}")
    if not name.strip() or not content.strip():
        raise ValueError("name va content bo'sh bo'lmasligi kerak")
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("metadata_json to'g'ri JSON bo'lishi kerak") from exc
    with closing(connect()) as db:
        if project_id:
            exists = db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
            if not exists:
                raise ValueError("project_id topilmadi")
        cur = db.execute(
            "INSERT INTO assets(project_id,kind,name,content,metadata,created_at) VALUES(?,?,?,?,?,?)",
            (project_id or None, kind, name.strip(), content, json.dumps(metadata, ensure_ascii=False), now()),
        )
        db.commit()
        return {"asset_id": cur.lastrowid, "kind": kind, "name": name.strip(), "project_id": project_id or None}


@mcp.tool()
def search_assets(query: str = "", kind: str = "", project_id: int = 0, limit: int = 30) -> list[dict[str, Any]]:
    """Search saved prompts, scenarios, characters, voice profiles and references."""
    limit = max(1, min(limit, 100))
    clauses, params = [], []
    if query:
        clauses.append("(name LIKE ? OR content LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    if project_id:
        clauses.append("project_id=?")
        params.append(project_id)
    sql = "SELECT * FROM assets" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with closing(connect()) as db:
        rows = db.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item["metadata"] or "{}")
            result.append(item)
        return result


@mcp.tool()
def save_continuity(project_id: int, part_number: int, final_frame_description: str,
                    next_part_start: str = "", reference_notes: str = "") -> dict[str, Any]:
    """Save the final-frame handoff between two video parts for visual continuity."""
    if part_number < 1 or not final_frame_description.strip():
        raise ValueError("part_number musbat, final_frame_description esa to'ldirilgan bo'lishi kerak")
    with closing(connect()) as db:
        if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("project_id topilmadi")
        cur = db.execute(
            "INSERT INTO continuity(project_id,part_number,final_frame_description,next_part_start,reference_notes,created_at) VALUES(?,?,?,?,?,?)",
            (project_id, part_number, final_frame_description, next_part_start, reference_notes, now()),
        )
        db.commit()
        return {"continuity_id": cur.lastrowid, "project_id": project_id, "part_number": part_number}


@mcp.tool()
def get_continuity(project_id: int) -> list[dict[str, Any]]:
    """Retrieve saved final-frame continuity notes for a project in part order."""
    with closing(connect()) as db:
        rows = db.execute("SELECT * FROM continuity WHERE project_id=? ORDER BY part_number,id", (project_id,)).fetchall()
        return [dict(r) for r in rows]


@mcp.tool()
def build_gemini_video_prompt(topic: str, duration_seconds: int = 10, part_number: int = 1,
                             total_parts: int = 1, visual_style: str = "Cinematic Action + Drama",
                             dialogue_language: str = "Uzbek", narrator_voice: str = "neutral, fast, consistent",
                             character_voice_direction: str = "distinct emotional voices by character",
                             previous_final_frame: str = "", scene_requirements: str = "") -> str:
    """Compose a structured English Gemini video prompt; spoken dialogue and on-screen text remain Uzbek."""
    if duration_seconds not in (5, 8, 10, 15):
        raise ValueError("duration_seconds uchun 5, 8, 10 yoki 15 soniyani tanlang")
    if not (1 <= part_number <= total_parts):
        raise ValueError("part_number total_parts oralig'ida bo'lishi kerak")
    return f'''Create Part {part_number} of {total_parts} of a cohesive cinematic video.\n\nTOPIC: {topic}\nDURATION: {duration_seconds} seconds\nVISUAL STYLE: {visual_style}. High production value, cinematic camera movement, realistic lighting, expressive acting, clear visual storytelling.\nLANGUAGE RULE: All spoken dialogue and all visible on-screen text must be in Uzbek. Do not add other languages on screen.\nVOICE DIRECTION: Narrator: {narrator_voice}. Character voices: {character_voice_direction}. Preserve each voice identity and speaking speed across all parts.\nMULTI-CHARACTER STORYTELLING: Use multiple relevant characters where appropriate; do not make the narrator the only speaker. Match every spoken line to the action and visuals being described.\nSCENE REQUIREMENTS: {scene_requirements or 'Build a clear beginning, development, and visual payoff.'}\nCONTINUITY INPUT: {previous_final_frame or 'This is the opening part; establish the visual world and character appearances.'}\nPART ENDING: End on a clean, stable, visually precise frame suitable for a screenshot reference. If another part follows, the next part must begin from exactly this frame, preserving character appearance, wardrobe, props, lighting, camera position, and spatial layout.\nQUALITY: No subtitles unless explicitly requested; no random text, visual glitches, inconsistent faces, or abrupt transitions.'''


class BearerAuth:
    """Minimal bearer-token gate for the public MCP endpoint."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and API_KEY:
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"").decode("utf-8", "ignore")
            expected = f"Bearer {API_KEY}"
            if not secrets.compare_digest(supplied, expected):
                body = b'{"error":"Unauthorized"}'
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    init_db()
    # Set MCP_API_KEY to a long random secret before public deployment.
    app = BearerAuth(mcp.streamable_http_app())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
