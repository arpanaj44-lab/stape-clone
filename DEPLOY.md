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
| `similarweb` | `SIMILARWEB_API_KEY` | Live monthly visits + paid share from Similarweb |

`AVG_CPC` (default `1.20`) is used to derive ad spend from paid visits when the
provider doesn't return spend directly.
