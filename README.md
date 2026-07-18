# Cuisine Recommendation Engine

A location aware food recommendation app.

Tell it your mood (savory, spicy, fresh, etc). It combines your location, current weather, and nearby restaurant data to suggest cuisines and specific places worth eating at right now, using a Claude LLM to reason through the data.


## What it does

1. You pick or enter a craving/preset and share your location.
2. The backend pulls current weather and a list of nearby open restaurants (via Google Places).
3. Claude reasons over your preset, the weather, and what's actually open nearby to plan a shortlist of cuisines and write a short "vibe" summary for top picks.
4. The frontend shows ranked restaurant results with distance, hours, and why each one fits.
5. You can upvote/downvote picks. Feedback is stored locally and nudges future rankings.

<br></br>
## Tech stack

**Backend**: Python, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [httpx](https://www.python-httpx.org/), SQLite for local feedback storage, and the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python). Talks to the **Google Places API** (New) for restaurant data.

**Frontend**: [React](https://react.dev/) + [Vite](https://vite.dev/), built to static files and served by [nginx](https://nginx.org/).

**Infrastructure**: Two Docker images (backend, frontend) orchestrated with **Docker Compose**, published on Docker Hub as [`democyborg/cuisine-engine-backend`](https://hub.docker.com/r/democyborg/cuisine-engine-backend) and [`democyborg/cuisine-engine-frontend`](https://hub.docker.com/r/democyborg/cuisine-engine-frontend).

nginx reverse proxies API requests from the frontend container to the backend container. The browser never talks to the backend directly, and no backend port is exposed to your host machine.

```
┌─────────────┐         ┌───────────────────────┐         ┌──────────────┐
│   Browser   │──HTTP─▶ │  frontend (nginx)     │ ──/api─▶│   backend    │
│  :8080      │         │  serves React build   │         │  (FastAPI)   │
└─────────────┘         │  proxies /api/* ─────▶│         │  :8000       │
                        └───────────────────────┘         │  (internal   │
                                                          │   only)      │
                                                          └──────┬───────┘
                                                                 │
                                                    ┌────────────┴────────────┐
                                                    ▼                         ▼
                                          Google Places API           Anthropic API
```

<br><br></br></br>
## Prerequisites

[Docker Desktop](https://www.docker.com/products/docker-desktop/). Works on macOS (Intel or Apple Silicon), Windows (via WSL2), and   Linux.

That's the only thing you need installed. Docker handles Python, Node, and every other dependency inside the containers.

<br></br>
## Get your API keys

You need two keys. Both have free tiers for personal/small scale use.

**Anthropic API key** (powers the cuisine reasoning):

1. Go to [console.anthropic.com](https://console.anthropic.com/) and sign up or log in.
2. Navigate to **Settings → API Keys**.
3. Click **Create Key**, name it, and copy the value (starts with `sk-ant-...`). You won't be able to see it again after leaving the page.
4. Add billing details if prompted.

**Google Places API key** (powers restaurant search):

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or select an existing one).
2. Go to **APIs & Services → Library**, search for **"Places API (New)"**, and enable it.
3. Go to **APIs & Services → Credentials → Create Credentials → API Key**.
4. Copy the generated key.
5. Restrict the key (recommended): edit it, restrict to "Places API (New)" only, and consider an IP restriction if you know where it'll run.

**Set up `backend/.env`:**

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` in any text editor:

```ini
GOOGLE_PLACES_KEY=your_google_places_new_api_key
ANTHROPIC_API_KEY=your_anthropic_key
CLAUDE_MODEL=claude-sonnet-4-6
SEARCH_RADIUS_M=8000
PER_CUISINE_LIMIT=8
CORS_ORIGINS=http://localhost:5173
```

Replace the two placeholder values with your real keys. The rest already has sane defaults.

**This file never leaves your machine.** `backend/.env` is listed in `.gitignore` and `.dockerignore`. It can't be committed to git or baked into a Docker image; it's only read from disk at container startup. See [Security notes](#security-notes).

<br><br></br></br>
## Setup

Two ways to run this. Both use the same `backend/.env` setup above.

<br></br>
### Option A: Run the published images (recommended)

Only two files needed: `docker-compose.yml` and a filled in `backend/.env`. No repo clone, no build step.

**1. Create a project folder and grab `docker-compose.yml`**

```bash
mkdir cuisine-engine && cd cuisine-engine
mkdir backend
curl -o docker-compose.yml https://raw.githubusercontent.com/demolishercyborg/cuisine-rec/main/docker-compose.yml
curl -o backend/.env.example https://raw.githubusercontent.com/demolishercyborg/cuisine-rec/main/backend/.env.example
```

(Or copy those two files by hand from the GitHub repo.)

**2.** Follow [Get your API keys](#get-your-api-keys) above.

**3. Run it**

```bash
docker compose up -d
```

Pulls the images straight from Docker Hub. No build required. First run downloads about 360MB combined; after that it starts in seconds.

**4.** Open **http://localhost:8080**.

To update later: `docker compose pull && docker compose up -d`.

<br></br></br></br>
### Option B: Clone and build from source

Use this if you want to change the code, not just run it.

**1. Clone the repo**

```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd cuisine-engine
```

**2.** Follow [Get your API keys](#get-your-api-keys) above.

**3. Build and run**

```bash
docker compose up --build
```

Builds both images from source and starts the stack. First run takes a minute or two; later runs are faster from cache.

**4.** Open **http://localhost:8080**.

<br><br></br></br>
### Stopping and background mode

```bash
docker compose down          # stop everything
docker compose up -d         # run in the background
docker compose up --build -d # background, rebuild from source
```
<br><br></br></br>
## Project structure

```
cuisine-engine/
├── docker-compose.yml       (orchestrates both containers)
├── backend/
│   ├── Dockerfile
│   ├── .env.example         (template, copy to .env and fill in your keys)
│   ├── requirements.txt
│   └── app/                 (FastAPI application code)
└── web/
    ├── Dockerfile            (multi stage: Node build, nginx serve)
    ├── nginx.conf             (serves the SPA, proxies /api/* to backend)
    ├── package.json
    └── src/                   (React source)
```

<br><br></br></br>
## How the pieces talk to each other

The **frontend** container serves the built React app on port 80 internally, published to your host as `localhost:8080`.

The **backend** container runs FastAPI on port 8000, but that port is not published to your host. It's only reachable from the frontend container over Docker's internal network. Your API keys' owning service isn't directly exposed to anything outside it.

When the browser calls `/api/recommend`, nginx (inside the frontend container) proxies that request to `http://backend:8000/recommend`. The browser never sees the backend's address or needs any API keys itself; only the backend ever touches `GOOGLE_PLACES_KEY` and `ANTHROPIC_API_KEY`.

`docker-compose.yml` waits for the backend's healthcheck to pass before starting the frontend, avoiding a race where nginx comes up before the backend is ready.

<br><br></br></br>
## Local (non Docker) development

For hot reloading while editing code instead of rebuilding images each time.

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd web
npm install
npm run dev
```

Vite's dev server runs on `http://localhost:5173` and is pre configured to proxy `/api/*` requests to `http://localhost:8000`.

Either way, `backend/.env` is what supplies your API keys. Same file, same setup as above.

<br></br>

## Security notes

Never commit `backend/.env`. It's git ignored by default; keep it that way. Only `backend/.env.example` (placeholder values) should ever be committed.

Keys are injected at container runtime, not build time. `docker-compose.yml` uses `env_file` to load `backend/.env` into the backend container's environment when it starts. The Dockerfiles never `COPY` this file, so it's physically impossible for a key to end up baked into an image layer. Even if you `docker push` the image to a public registry, no secret goes with it.

The backend port is not published to the host. Only the frontend's port (`8080`) is reachable from outside Docker's internal network.

If a key is ever accidentally exposed, revoke and regenerate it immediately from the same consoles linked above.

<br></br>

## Troubleshooting

**`docker compose up` fails immediately citing `backend/.env`**: you skipped the [API keys setup](#get-your-api-keys). Copy `.env.example` to `.env` and fill it in first.

**Recommendations fail with a 500 error**: check `docker compose logs backend`. This almost always means one of your API keys is invalid, unset, or the Google Places API isn't enabled on your Google Cloud project.

**Port 8080 already in use**: another process is using that port. Stop it, or change the host side port in `docker-compose.yml` (the `"8080:80"` line under `frontend.ports`).

**Changes to code aren't showing up**: images are built once from a source snapshot. Editing source files doesn't affect an already running container. Re-run `docker compose up --build`, or use the local dev setup above for live reloading.
