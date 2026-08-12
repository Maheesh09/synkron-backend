# Synkron - Backend

Synkron is an AI agent that keeps documentation honest. Every time a developer pushes code to a GitLab repository, Synkron reads the diff, figures out which documentation files are now wrong, rewrites only the affected sections, and opens a merge request with the fix. Nobody has to remember to update the README. The merge request simply shows up.

This repository is the backend service: a FastAPI application that receives GitLab push webhooks, runs the documentation pipeline, and serves the dashboard API used by the frontend.

---

## What It Does

Documentation rots. Code changes daily, docs get fixed whenever someone finally notices they are stale, and the gap between the two is where new developers lose hours. Most teams know this and still fall behind, because updating docs is a separate chore that competes with shipping.

Synkron removes the chore. Keeping docs current becomes a side effect of pushing code, the same way a test suite runs in CI without anyone clicking a button.

---

## How It Works

A developer pushes code normally. GitLab sends a push event to the webhook endpoint. Synkron validates the token, ignores anything not worth acting on (empty pushes and its own bot commits, so it never reacts to itself), and drops the real work onto a Cloud Tasks queue. The web request returns immediately so GitLab is never left waiting.

From there, four agents run in sequence:

**Code Analyzer** reads the commit diff, discards noise such as lock files and test fixtures, and asks Gemini to describe what actually changed in plain language. It returns a short summary and a handful of keywords a developer would search for in the docs. If the change is a pure refactor with no behaviour difference, it returns nothing and the run stops here.

**Impact Mapper** takes those keywords, scans the repository's documentation files (Markdown, reStructuredText, OpenAPI specs, and similar), scores each one for relevance, and keeps only those above a confidence threshold. If nothing clears the bar, the run stops.

**Doc Writer** rewrites only the sections that describe the changed behaviour in each affected document, leaving everything else untouched: same headings, same tone, same structure.

**PR Creator** creates a branch named after the commit, commits the updated docs, and opens a merge request titled `Docs: [summary]`. Then it waits for a human to review.

### The Feedback Loop

When a reviewer edits one of Synkron's merge requests before merging it, those edits are a signal: this is how the team actually wants their docs to read. Synkron watches for merge events on its own merge requests, captures the difference between what it wrote and what was merged, and stores those correction patterns in MongoDB. Future runs on the same repository draw on these patterns to match the team's voice.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.118 |
| Language | Python 3.11 |
| AI models | Gemini 3.1 Flash Lite + Gemini 3.5 Flash via AI Studio |
| Database | MongoDB Atlas (Motor async driver) |
| Queue | Google Cloud Tasks |
| Auth validation | Firebase Admin SDK |
| Hosting | Google Cloud Run |

---

## Prerequisites

* Python 3.11 or newer
* A MongoDB Atlas cluster (the free M0 tier is sufficient)
* A GitLab personal access token with the `api` scope
* A Gemini API key from [Google AI Studio](https://aistudio.google.com)
* A Google Cloud project with Cloud Run and Cloud Tasks enabled (for production)

---

## Local Development

**1. Clone and create a virtual environment**

```bash
git clone https://github.com/Maheesh09/synkron-backend.git
cd synkron-backend

python -m venv venv

# macOS or Linux
source venv/bin/activate

# Windows PowerShell
venv\Scripts\activate
```

**2. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**3. Create your environment file**

```bash
cp .env.example .env
```

Open `.env` and fill in your values. See the Environment Variables section below for what each one does.

**4. Start the server**

`LOCAL_DEV=true` bypasses Cloud Tasks and calls the internal pipeline endpoint directly, so you can run the whole thing without any cloud setup.

```bash
# macOS or Linux
LOCAL_DEV=true uvicorn app.main:app --reload --port 8080

# Windows PowerShell
$env:LOCAL_DEV="true"
uvicorn app.main:app --reload --port 8080
```

**5. Trigger a run manually**

You can test the pipeline without waiting for a real push by calling the internal endpoint directly:

```bash
curl -X POST http://localhost:8080/internal/run-pipeline \
  -H "X-Internal-Token: your_internal_secret" \
  -H "Content-Type: application/json" \
  -d '{"after": "FULL_COMMIT_SHA", "project": {"id": YOUR_GITLAB_PROJECT_ID}}'
```

Watch the server logs. Each agent announces itself as it runs, and if there are docs worth changing, a merge request URL appears at the end.

**6. Connect a real GitLab repository**

Expose your local server with a tunnel such as ngrok, then add a webhook in your GitLab repository settings pointing at `https://your-tunnel-url/webhook/gitlab`. Enable Push events and Merge request events, and set the secret token to match `GITLAB_WEBHOOK_SECRET` in your `.env`. After that, a normal `git push` runs the full pipeline.

---

## Environment Variables

Copy `.env.example` to `.env` and set these values before running.

| Variable | Required | Description |
|---|---|---|
| `GITLAB_PAT` | Yes | Personal access token with the `api` scope. Used to read commits and open merge requests. |
| `GITLAB_WEBHOOK_SECRET` | Yes | Any string. Set the same value as the secret token when you register the webhook in GitLab. |
| `GEMINI_API_KEY` | Yes | API key from Google AI Studio. Used by the direct REST pipeline. |
| `MONGODB_URI` | Yes | MongoDB Atlas connection string. |
| `MONGODB_DB_NAME` | No | Database name. Defaults to `synkron-cluster`. |
| `SERVICE_URL` | Yes | The public base URL of this service. Cloud Tasks uses it to call back into the internal endpoints. |
| `INTERNAL_SECRET` | Yes | A random string that protects the internal endpoints from being called by anyone other than the queue. |
| `FIREBASE_PROJECT_ID` | Yes | The Firebase project ID used to verify user ID tokens from the frontend. |
| `GOOGLE_CLOUD_PROJECT` | No | Your Google Cloud project ID. Required when running with Cloud Tasks. |
| `GCP_REGION` | No | Cloud region. Defaults to `asia-south1`. |
| `LOCAL_DEV` | No | Set to `true` for local development. Bypasses Cloud Tasks. Never set this in production. |

---

## Deploying to Cloud Run

**1. Create the Cloud Tasks queue**

```bash
gcloud tasks queues create synkron-pipeline-queue --location YOUR_REGION
```

**2. Grant the Cloud Run service account permission to enqueue tasks**

```bash
PROJECT_NUM=$(gcloud projects describe YOUR_PROJECT_ID --format="value(projectNumber)")

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"
```

**3. Create `env.yaml` with your production values**

```yaml
GITLAB_PAT: "your_token"
GITLAB_WEBHOOK_SECRET: "any_non_empty_string"
GEMINI_API_KEY: "your_key"
MONGODB_URI: "your_atlas_uri"
MONGODB_DB_NAME: "synkron-cluster"
SERVICE_URL: "https://YOUR_CLOUD_RUN_URL"
INTERNAL_SECRET: "a_random_secret"
FIREBASE_PROJECT_ID: "your_firebase_project"
LOCAL_DEV: "false"
GOOGLE_CLOUD_PROJECT: "your_project_id"
GCP_REGION: "your_region"
```

**4. Deploy**

```bash
gcloud run deploy synkron-backend \
  --source . \
  --region YOUR_REGION \
  --allow-unauthenticated \
  --cpu 1 \
  --memory 1Gi \
  --timeout 600 \
  --env-vars-file env.yaml
```

**5. Update the queue to prevent retry storms**

```bash
gcloud tasks queues update synkron-pipeline-queue \
  --location YOUR_REGION \
  --max-attempts=1 \
  --max-concurrent-dispatches=1
```

This ensures one push always maps to exactly one pipeline attempt with no concurrent overlap.

---

## API Reference

### Public

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Service info |
| `GET` | `/health` | Health check for uptime monitoring |
| `POST` | `/webhook/gitlab/{project_id}` | Receives GitLab push and merge request events |

### Dashboard (requires Firebase ID token as Bearer)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/repos` | Lists connected repositories for the signed in user |
| `POST` | `/api/repos/connect` | Connects a new GitLab repository |
| `DELETE` | `/api/repos/{id}` | Removes a connected repository |
| `POST` | `/api/repos/{id}/rotate-token` | Rotates the webhook token for a repository |
| `GET` | `/api/runs` | Lists recent pipeline runs |
| `GET` | `/api/health` | Run counts and success rate |

### Internal (requires `X-Internal-Token` header)

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/run-pipeline` | Runs the full documentation pipeline for one commit |
| `POST` | `/internal/process-feedback` | Records a human correction from a merged MR |

---

## Project Layout

```
app/
  main.py                FastAPI app, route wiring, startup and shutdown
  config.py              Settings loaded from environment variables
  database.py            MongoDB connection and index setup
  auth.py                Firebase ID token verification
  routers/
    webhook.py           Receives GitLab events and guards against loops
    pipeline.py          Internal endpoint that runs the pipeline
    dashboard.py         Read-only stats and run history (auth-gated)
  services/
    gitlab_mcp.py        GitLab REST client (commits, files, branches, MRs)
    gemini.py            Gemini model wrapper for the REST pipeline
    cloud_tasks.py       Cloud Tasks dispatch
    feedback.py          Converts human MR edits into correction patterns
  agents/
    orchestrator.py      Sequences the four agents
    code_analyzer.py     Agent 1 — understands what changed
    impact_mapper.py     Agent 2 — finds relevant doc files
    doc_writer.py        Agent 3 — rewrites affected sections
    pr_creator.py        Agent 4 — opens the merge request
  models/
    pipeline_run.py      MongoDB document shapes
```

---

## Design Notes

**One service, not a fleet.** The pipeline is naturally sequential, the deadline was real, and a single well organised service is easier to reason about than several services talking to each other over a network. The folder structure keeps the layers cleanly separated, so splitting is straightforward later if needed.

**Quality over volume.** Synkron lives or dies on whether developers merge its work without heavy editing. A tool that opens noisy or wrong merge requests gets ignored within a week. Everything in the pipeline, from the relevance threshold to the instruction that the Doc Writer should change as little as possible, exists to protect that one outcome.

**Webhook security.** Each connected repository gets its own random token, stored as a SHA256 hash in MongoDB. A single shared secret (a common pattern in similar tools) is a single point of failure: one leaked token compromises every repository. Synkron avoids that entirely.

---

## Current Limitations

* Works with GitLab. GitHub support is not wired up yet.
* The feedback loop pays off with steady use. Out of the box the Doc Writer is only as good as its prompt and the model.
* Documentation quality should always be reviewed by a human before merging.

---

## License

MIT — see [LICENSE](LICENSE).
