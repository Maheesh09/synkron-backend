# Synkron

Synkron keeps documentation honest. Every time someone pushes code to a GitLab repository, Synkron reads what changed, figures out which documents are now wrong, rewrites only those parts, and opens a merge request with the fix. Nobody has to remember to update the README. The merge request simply shows up, and a person decides whether to merge it.

This repository is the backend: a FastAPI service that listens for GitLab push events and runs the documentation pipeline behind them.

Status: active development, built under a hackathon deadline. Treat it as early and read the limitations near the end before relying on it.

## The problem it solves

Documentation rots. Code changes daily, docs get fixed whenever someone finally notices they are stale, and the gap between the two is where new developers lose hours and where bug reports get filed against behavior that no longer exists. Most teams know this and still fall behind, because updating docs is a separate chore that competes with shipping.

Synkron removes the separate chore. Keeping docs current becomes a side effect of pushing code, the same way a test suite runs in CI without anyone clicking a button.

## Two execution paths

Synkron can run the pipeline in two distinct ways, toggled via environment variables:

1. **Direct REST Pipeline (Default)**: A lightweight, 4-agent sequential workflow that connects directly to GitLab via REST. It includes a feedback loop that learns from human edits to MRs over time.
2. **MCP ADK Runner Path**: A single Google ADK `LlmAgent` running locally against the Gemini API. Instead of REST, it launches the official `@zereight/mcp-gitlab` server as a local subprocess and executes all GitLab operations through the Model Context Protocol (MCP).

## How it works, start to finish

There is one way in, regardless of which execution path is active.

A developer pushes code as they normally would. GitLab sends a push event to Synkron's webhook. Synkron inspects the event, ignores anything not worth acting on (empty pushes, and crucially its own bot commits so it never reacts to itself), and drops the real work onto a background queue. The web request returns right away, so GitLab is never left waiting.

The queued job runs the pipeline. If the default Direct REST pipeline is used, four agents run in order:

1. Code Analyzer. Reads the commit diff, discards noise such as lock files and test fixtures, and asks the model to describe what actually changed in plain language. It returns a short summary plus a handful of keywords a developer would search for in the docs. If the change is a pure refactor with no behavior difference, it returns nothing and the run stops here.

2. Impact Mapper. Takes those keywords and scans the repository's documentation files (Markdown, reStructuredText, OpenAPI specs, and similar). It scores each document for how likely it is to be affected and keeps only the ones above a confidence threshold. If nothing clears the bar, the run stops.

3. Doc Writer. For each affected document, it rewrites only the sections that describe the changed behavior. It is instructed to leave everything else untouched: the same headings, the same tone, the same structure. The aim is a change a careful human would have made, not a wholesale rewrite of the file.

4. PR Creator. Creates a branch named after the commit, commits the updated docs under the synkron-bot author, and opens a merge request with a clear title and description. Then it stops and waits for a person to review.

*(If the MCP ADK Runner path is active, a single agent handles all these steps via MCP tool calls).*

Every run is written to the database with its status, how long it took, and the merge request it produced, so you can always see what Synkron has been doing.

## The feedback loop

This is the part meant to make Synkron improve rather than stay average.

When a reviewer edits one of Synkron's merge requests before merging it, those edits carry information: this is how the team actually wants their docs to read. Synkron watches for merge events on its own merge requests, captures the difference between what it wrote and what was merged, and stores those correction patterns. The Doc Writer can then lean on them to match the team's voice instead of guessing at it.

An honest caveat: this only pays off with steady use. A team that adopts Synkron and keeps correcting it will watch the quality climb. A team that tries it once and walks away will not see the benefit.

## Who actually touches it

Almost nobody, and that is on purpose. Synkron can run in two roles, and this project is built for the first one.

Operator deployment. One person sets Synkron up, deploys it, and adds a webhook to each repository they want covered. After that, the developers on those repositories change nothing about how they work. They push code; merge requests appear. There is no dashboard they sign into, no account to create, no plugin to install. The reasoning is simple: the easiest tool to adopt is one that asks for nothing.

The other role, a shared service hosting many separate customers, is not what this codebase is for. The data model and configuration assume a single operator running their own instance.

## Project layout

```
synkron-backend/
  app/
    main.py              FastAPI app, route wiring, startup and shutdown
    config.py            Settings loaded from environment variables
    database.py          MongoDB connection and index setup
    routers/
      webhook.py         Receives GitLab events
      pipeline.py        Internal endpoints that run the pipeline and feedback
      dashboard.py       Read only stats and run history
    services/
      gitlab_mcp.py      GitLab API client (commits, files, branches, merge requests)
      gemini.py          Wrapper around the Gemini models
      cloud_tasks.py     Background queue dispatch
      feedback.py        Turns human edits into stored correction patterns
    agents/
      orchestrator.py    Runs the four agents in sequence
      code_analyzer.py   Agent 1
      impact_mapper.py   Agent 2
      doc_writer.py      Agent 3
      pr_creator.py      Agent 4
    agent_builder/       Optional path for running on a hosted agent engine
    models/
      pipeline_run.py    Database document shapes
  scripts/               Operational scripts
  requirements.txt
  .env.example
```

## The endpoints

Public.

GET / returns basic service information.

GET /health is a simple health check for uptime monitoring.

POST /webhook/gitlab is where GitLab sends events. It is guarded by a shared secret token that GitLab includes on every call.

Internal. These are protected by a separate secret header and are meant to be called by the queue, not by people.

POST /internal/run-pipeline runs the full documentation pipeline for one commit.

POST /internal/process-feedback records a human correction.

Dashboard. These are read only.

GET /api/runs lists recent pipeline runs.

GET /api/health returns run counts and a success rate across everything Synkron has processed.

GET /api/repos lists the repositories Synkron is aware of.

## What you need first

Python 3.11 or newer.

Node.js and npm (required for the MCP path to spawn the GitLab MCP server). Once installed, run `npm install -g @zereight/mcp-gitlab` so the server starts instantly.

A MongoDB database. The free Atlas tier is enough to begin with.

A GitLab personal access token with the api scope, so Synkron can read commits and open merge requests.

A Gemini API key (or Google AI Studio key).

## Running it on your machine

Create and activate a virtual environment, then install the dependencies.

```
python -m venv venv

# Windows
venv\Scripts\activate

# macOS or Linux
source venv/bin/activate

pip install -r requirements.txt
```

Copy the example environment file and fill in your own values.

```
cp .env.example .env
```

For local work there is a LOCAL_DEV switch. With it turned on, Synkron skips the cloud queue and calls its own internal endpoint directly, which lets you run the whole thing with no cloud setup at all. Start the server like this on macOS or Linux:

```
LOCAL_DEV=true uvicorn app.main:app --reload --port 8080
```

On Windows PowerShell, set the variable first, then start the server:

```
$env:LOCAL_DEV="true"
uvicorn app.main:app --reload --port 8080
```

You can trigger a run by hand without waiting for a real push. Send a commit SHA and a project ID to the internal endpoint, using the internal secret from your .env file:

```
curl -X POST http://localhost:8080/internal/run-pipeline -H "X-Internal-Token: your_internal_secret" -H "Content-Type: application/json" -d "{\"after\": \"FULL_COMMIT_SHA\", \"project\": {\"id\": YOUR_PROJECT_ID}}"
```

Watch the server logs. Each agent announces itself as it runs, and if there are docs worth changing, a merge request URL comes back at the end.

To test the real path, expose your local server with a tunnel such as ngrok and point a GitLab webhook at the public address. After that, an ordinary push sets the whole thing in motion.

## Configuration

Synkron reads everything from environment variables. Here is what each one does.

GITLAB_PAT is the personal access token used for every GitLab call. It needs the api scope so Synkron can create branches and merge requests, not just read.

GITLAB_WEBHOOK_SECRET is a shared secret. GitLab sends it on each webhook call, and Synkron rejects any call where it does not match.

GEMINI_API_KEY is the key for the Gemini models used by the default direct REST pipeline.

USE_AGENT_BUILDER switches Synkron to use the MCP ADK Runner path when set to `true`.

GOOGLE_API_KEY is used by the MCP ADK Runner path. It defaults to GEMINI_API_KEY if left blank.

GOOGLE_GENAI_USE_VERTEXAI should be set to `FALSE` to ensure the ADK Runner uses the free-tier Gemini API rather than billing a Vertex AI project.

MONGODB_URI is the connection string for your MongoDB instance.

MONGODB_DB_NAME is the name of the database to use.

INTERNAL_SECRET guards the internal endpoints, so only the queue can start the pipeline.

SERVICE_URL is the public base address of the deployed service. The queue uses it to call back into the internal endpoints.

GOOGLE_CLOUD_PROJECT and GCP_REGION are your Google Cloud project and region, used when running on Cloud Run with Cloud Tasks.

AGENT_ENGINE_RESOURCE is optional. Set it only if you deployed the agent to Vertex AI Reasoning Engine using the provided scripts.

LOCAL_DEV is for local work only. Set it to true to bypass the cloud queue while developing, and never set it in production.

## Adding a repository

Once Synkron is deployed, you cover a repository by giving it a webhook. In GitLab, open the repository settings, go to Webhooks, and add one.

Set the URL to your service address followed by /webhook/gitlab.

Set the secret token to the same value as GITLAB_WEBHOOK_SECRET.

Enable Push events. Also enable Merge request events if you want the feedback loop to capture human edits.

Save it, use GitLab's test button to confirm Synkron answers, and that is the whole setup. From then on, every push to that repository runs through the pipeline.

## How it runs in production

The intended setup is Google Cloud Run for the service and Cloud Tasks for the queue. The webhook answers fast and hands the job to the queue. The queue then calls the internal endpoint, which does the slow work of talking to the model and to GitLab. This keeps the webhook responsive and gives the heavy work automatic retries when something fails partway through.

MongoDB holds three kinds of records: the pipeline runs themselves, the repositories under management, and the correction patterns learned from human edits.

## Design choices worth knowing

It is one service, not a fleet of small ones. The pipeline is naturally sequential, the deadline was real, and a single well organized service is easier to reason about than several services talking to each other over the network. The folders keep the layers cleanly separated, so it can be split later if it ever needs to be.

The database is MongoDB, and the code assumes it. The document model and the async driver run through the entire backend, so swapping to another database would be a rewrite rather than a config change. That tradeoff was made deliberately for speed of building.

Quality is the thing that matters, not volume. Synkron lives or dies on whether people merge its work without heavy editing. A tool that opens noisy or wrong merge requests gets ignored within a week. Everything in the pipeline, from the relevance threshold to the rule that the writer should change as little as possible, exists to protect that one outcome.

## Current limitations

It works with GitLab. GitHub and other hosts are not wired up.

The feedback loop needs ongoing use before its value shows. Out of the box, the Doc Writer is only as good as its prompt and the underlying model.

Documentation quality is still being tuned, and merge requests should be reviewed by a human, not merged blindly.

## License

See the LICENSE file in this repository.
