# Deploy & get a public link

You don't need an IDE or Python. Pick one path.

---

## Option A — Render free tier (recommended, gives a public URL)

You'll need two free accounts: **GitHub** (to hold the code) and **Render**
(to run it). ~5–10 minutes.

### 1. Put the code on GitHub
- Go to <https://github.com/new>, create an empty repo (e.g. `tracking-checker`).
- On the new repo page, click **uploading an existing file**.
- Drag in **all** the files from this `tracking-checker` folder (including
  `Dockerfile`, `render.yaml`, `requirements.txt`, the `.py` files and the
  `templates/` folder). Commit.

### 2. Deploy on Render
- Sign up / log in at <https://render.com> (the free plan is fine).
- Click **New +** → **Blueprint**.
- Connect your GitHub and pick the repo. Render reads `render.yaml` and
  configures everything automatically.
- Click **Apply**. First build takes a few minutes (it downloads the browser image).
- When it's live you get a URL like `https://tracking-checker-xxxx.onrender.com`.
  Open it and scan a site.

> Free instances sleep after inactivity, so the first request after a nap takes
> ~30–60s to wake. Fine for testing.

### 3. (Optional) Enable ad-spend / users-not-tracked estimates
In Render → your service → **Environment**:
- Set `TRAFFIC_PROVIDER` = `similarweb`
- Add `SIMILARWEB_API_KEY` = your key
- Optionally set `AVG_CPC` (default `1.20`)
Save; Render redeploys. Without this, every other section still works — only the
"Tracking loss impact" box shows a "connect a provider" note.

---

## Option B — Docker on your own machine (local link only)

If you have (or install) **Docker Desktop** — no Python needed:

```bash
cd tracking-checker
docker build -t tracking-checker .
docker run -p 8000:8000 tracking-checker
```
Open <http://localhost:8000>.

To enable estimates, add env flags:
```bash
docker run -p 8000:8000 \
  -e TRAFFIC_PROVIDER=similarweb -e SIMILARWEB_API_KEY=your_key \
  tracking-checker
```
Try the demo numbers without any key using the mock provider:
```bash
docker run -p 8000:8000 -e TRAFFIC_PROVIDER=mock tracking-checker
```

---

## Option C — Railway / Fly.io
Both read the same `Dockerfile`. On Railway: **New Project → Deploy from GitHub
repo**, and it builds the Dockerfile automatically. Set the same env vars under
the service's **Variables** tab.

---

## Traffic provider options (recap)

| `TRAFFIC_PROVIDER` | Needs | Behaviour |
|---|---|---|
| *(unset)* / `none` | — | Estimates section shows a "connect a provider" note |
| `mock` | — | Deterministic demo numbers (clearly labelled) — good for a quick look |
| `manual` | `MONTHLY_VISITS` (+ optional `MONTHLY_AD_SPEND`, `PAID_SHARE`) | Uses your own numbers |
| `apify` | `APIFY_TOKEN` (+ optional `APIFY_ACTOR_ID`) | Runs an Apify traffic actor; visits + paid share + CPC |
| `similarweb` | `SIMILARWEB_API_KEY` | Live monthly visits + paid share from Similarweb |

`AVG_CPC` (default `1.20`) is used to derive ad spend from paid visits when the
provider doesn't return spend directly.

### Getting an Apify token (free tier)

1. Sign up at <https://console.apify.com/sign-up> (free plan includes monthly usage credits).
2. In the Apify Console, open **Settings → Integrations** (or **API & Integrations**).
3. Copy your **Personal API token** (starts with `apify_api_...`).
4. Set env vars on your host (Render → your service → **Environment**):
   - `TRAFFIC_PROVIDER` = `apify`
   - `APIFY_TOKEN` = *your token*
   - *(optional)* `APIFY_ACTOR_ID` = e.g. `pro100chok~similarweb-scraper` (the default) or another traffic actor in `username~actor-name` form.
5. Save → the service redeploys → the "Tracking loss impact" box fills in.

> These actors are pay-per-use (~$0.70–$1 per 1,000 domains); the free monthly
> credit covers hundreds of scans. The adapter parses the actor's output
> defensively, so if a particular actor's numbers don't populate, switch
> `APIFY_ACTOR_ID` to another traffic actor — no code change needed.

---

## Troubleshooting

**`failed to read dockerfile: open Dockerfile: no such file or directory`**
Render can't find the `Dockerfile` at the repo root. Almost always the files got
uploaded **inside a subfolder** (e.g. `stape-clone/tracking-checker/Dockerfile`).
Fix either way:

- **Easiest:** make the repo root contain the files directly — `Dockerfile`,
  `app.py`, `render.yaml`, `requirements.txt` and the `templates/` folder should
  appear on the repo's main page, *not* inside another folder. Re-upload so
  nothing is nested. Then in Render click **Manual Deploy → Clear build cache & deploy**.
- **Or keep the subfolder:** in Render → service → **Settings**, set
  **Root Directory** to the subfolder (e.g. `tracking-checker`) and redeploy.

To check your repo layout: open the repo on GitHub — you should see `Dockerfile`
in the file list on the landing page. If instead you see a single folder, click
into it; that's the nesting to remove.
