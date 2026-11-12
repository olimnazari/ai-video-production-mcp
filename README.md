# AI VIDEO PRODUCTION MCP — Cloud Edition

A starter remote MCP server for Claude. It manages video projects, prompts, scenarios, characters, voice profiles, and final-frame continuity notes. It also composes structured Gemini video prompts with Uzbek dialogue/on-screen text requirements.

## Included MCP tools

- `create_project`, `list_projects`, `update_project`
- `save_asset`, `search_assets`
- `save_continuity`, `get_continuity`
- `build_gemini_video_prompt`

Data is stored in SQLite. Mount a persistent disk at the directory used by `DATABASE_PATH` when deploying.

## Run locally

Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export MCP_API_KEY="replace-with-a-long-random-secret"
export DATABASE_PATH="./data/video_production.sqlite3"
python server.py
```

The Streamable HTTP MCP endpoint is normally `http://localhost:8000/mcp`.

## Deploy as a cloud service

Deploy this folder to a Python host that supports persistent disks (for example, Render or Railway):

- Build command: `pip install -r requirements.txt`
- Start command: `python server.py`
- Environment variable: `MCP_API_KEY` = a long random secret
- Environment variable: `DATABASE_PATH` = path on your persistent disk, e.g. `/var/data/video_production.sqlite3`
- Persistent disk mount: `/var/data`
- Health check: `/` is not an application health endpoint; use the host's TCP/service health or configure an HTTP health route in a production hardening pass.

The server listens on `0.0.0.0:$PORT` and requires `Authorization: Bearer <MCP_API_KEY>` when `MCP_API_KEY` is set.

## Add to Claude

In Claude, open **Customize → Connectors → Add custom connector** (wording can vary by client), name it `AI VIDEO PRODUCTION`, and enter the deployed public MCP URL ending in `/mcp`. Configure authentication as a fixed request header if your Claude connector setup offers it:

`Authorization: Bearer YOUR_MCP_API_KEY`

If the UI does not expose fixed request headers for your account, implement OAuth for production rather than disabling authentication.

## Important production notes

- Do not commit API keys or credentials to source control.
- Use a persistent disk; ephemeral container storage can be lost on redeploy.
- This starter stores text and metadata only. It does not upload or host audio/image/video files.
- Gemini video generation is not invoked yet. Add a Gemini API integration only after an API key and desired generation workflow are configured.
- Review every tool permission before connecting Claude. The API key grants access to the server's stored project data.
