# India Talent Scout

Lite HR recruiter web app for **India-focused talent pools**: search candidates by skill keywords, location, experience, and recency. Candidates **opt in** at `/join`, or recruiters **import CSV** exports from paid portals (Naukri Resdex, Shine, etc.).

This app **does not** log into or scrape Naukri, Indeed, LinkedIn, or other job portals. Use only consenting candidates or data you are entitled to import.

## Stack

- Python 3.12, FastAPI, SQLAlchemy, Alembic
- Jinja2 + HTMX (minimal UI)
- SQLite locally; PostgreSQL on Render (recommended)
- Optional **Gemini Flash** for resume skill extraction and search reranking

## Run locally

Requires **Python 3.10+** locally (Docker uses 3.12).

```bash
cd india-talent-scout
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8081
```

Open [http://localhost:8081](http://localhost:8081). Default recruiter password: `recruiter` (set `RECRUITER_PASSWORD`).

With `DEMO_SEED=true`, 15 demo India profiles load when the database is empty.

## Configuration

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | `sqlite:///./data/talent.db` (dev) or Postgres connection string |
| `RECRUITER_PASSWORD` | Password for `/recruit/login` |
| `SESSION_SECRET` | Signs recruiter session cookie |
| `GEMINI_API_KEY` | Optional; improves resume parsing and rerank |
| `GEMINI_MODEL` | Default `gemini-2.0-flash` |
| `DEMO_SEED` | `true` to seed demo candidates on empty DB |
| `STORAGE_DIR` | Resume upload directory |
| `PORT` | Listen port. Default `8081` |
| `PORTAL_LIVE_LOGIN` | `true` to probe portal login URLs (no CAPTCHA bypass) |
| `JD_TTL_HOURS` | How long a JD-match workspace is kept. Default `24` |
| `OAUTH_REDIRECT_BASE` | Public origin for Gmail/Outlook draft connect, no trailing path |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Optional. Gmail draft connect |
| `MICROSOFT_OAUTH_CLIENT_ID` / `MICROSOFT_OAUTH_CLIENT_SECRET` | Optional. Outlook draft connect |

## Recruiter workflow

1. Log in at `/recruit/login`.
2. **Portal logins** (`/recruit/portals`) — open each portal URL, save recruiter username/password (encrypted). Test connection.
3. **Search** — pick one or more portals, optional **Pull from selected portals**, then search by skills/city/years. Results can combine local pool + synced portal profiles.
4. **Import CSV** — [download template](/recruit/import/template.csv) (after login). Columns:

   `name,email,phone,city,years_experience,skills,last_active_at,source_portal,resume_url_or_notes,profile_summary`

5. **Shortlist** — status and notes per candidate.
6. **JD match** (`/recruit/jd`) — pick a folder of resumes in the browser, rank them against a job description, filter, and download Excel. Original files are not stored. The workspace is private to the recruiter session and expires (`JD_TTL_HOURS`). Mail buttons save drafts only; nothing is sent automatically.

Sample files for a dry run: [`samples/jd.txt`](samples/jd.txt) and [`samples/resumes/`](samples/resumes/).

### JD match data flow

1. The browser reads a local folder (`showDirectoryPicker`, or a directory file input / drop) and uploads files in batches of 15.
2. The server extracts text (PDF, DOCX, TXT; OCR for images and empty PDFs when Tesseract and Poppler are installed), then keeps structured fields only.
3. Ranking is deterministic: must-have skills, nice-to-have skills, experience, and location. Weights are on the form. `JS` counts as JavaScript and `k8s` as Kubernetes.
4. Filters are AND-combined and remembered on the workspace. Export filtered uses the current filters; export all ignores them.
5. Optional Gemini extraction is used only when `GEMINI_API_KEY` is set. Email and phone values that do not appear in the file are dropped.

**Portal sync note:** Naukri, Shine, Indeed, Foundit, and Instahyre do not expose free resume APIs. With default settings, saved credentials enable **demo sync** (sample profiles tagged by portal). Set `PORTAL_LIVE_LOGIN=true` only to check whether login pages are reachable. Production use requires licensed API connectors in [`app/portals/base.py`](app/portals/base.py) or CSV export import.

## Candidate workflow

Visit `/join`, upload PDF/DOCX/TXT, enter skills, and consent to share the profile.

## Deploy on Render (free)

1. Push this repo to GitHub.
2. [Render](https://render.com) → **New → Blueprint** → select repo (`render.yaml` provisions web + free Postgres).
3. Set `RECRUITER_PASSWORD` and optional `GEMINI_API_KEY`.
4. Open the `*.onrender.com` URL. Free tier sleeps when idle; first request after sleep may take ~1 minute.

## Commercial portal integrations (future)

See [`app/plugins.py`](app/plugins.py) for a `CandidateSourceProvider` hook. Paid APIs (Naukri Resdex, Mustakbil, etc.) can be added without changing the search UI.

## Tests

```bash
pytest
```
