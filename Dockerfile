# Playwright's official image ships Chromium + all OS libraries preinstalled,
# which removes the single biggest source of deployment pain.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render/Railway/Fly inject the port to listen on via $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at runtime. Proxy-header flags make request.base_url
# reflect the real public https URL (used for shareable report links).
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*"
