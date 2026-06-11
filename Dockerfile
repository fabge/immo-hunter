FROM python:3.12-slim

WORKDIR /app

COPY hunter/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Fallback copy; on terra the repo is bind-mounted over /app (pa pattern),
# so source/config/db live on the host and survive rebuilds.
COPY . /app

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "hunter.run", "--loop"]
