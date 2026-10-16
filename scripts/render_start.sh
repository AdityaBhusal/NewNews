#!/bin/sh
# Render free-tier starter: run the worker beside the API in ONE web service.
# (Free plans allow web services only — no Background Worker service. Production
# splits this: api = Web Service, worker = Background Worker, same image.)
# Invoked as the service's Docker Command:  sh scripts/render_start.sh
set -e
python -m app.worker &
exec uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
