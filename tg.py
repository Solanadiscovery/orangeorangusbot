"""Telegram Bot API: chiamate con retry, backoff e rispetto dei limiti (429 retry_after)."""
import json, os, time, urllib.error, urllib.request, uuid


class TelegramError(Exception):
    def __init__(self, code, description):
        super().__init__(f"{code}: {description}")
        self.code, self.description = code, description


def call(method, fields, retries=4, sleep=time.sleep):
    token = os.environ.get("BOT_TOKEN", "").strip().removeprefix("bot")
    if not token:
        raise TelegramError(0, "BOT_TOKEN mancante")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", json.dumps(fields).encode(),
                                 {"Content-Type": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode() or "{}")
            wait = body.get("parameters", {}).get("retry_after")
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                sleep(wait or 2 ** attempt)
                continue
            raise TelegramError(e.code, body.get("description", ""))  # il token non compare mai nei messaggi
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
            sleep(2 ** attempt)


def upload(method, fields, file_field, path, retries=2, sleep=time.sleep):
    """Send a local file (multipart/form-data), e.g. sendDocument. Returns the Telegram result."""
    token = os.environ.get("BOT_TOKEN", "").strip().removeprefix("bot")
    if not token:
        raise TelegramError(0, "BOT_TOKEN mancante")
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    with open(path, "rb") as f:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{os.path.basename(path)}"\r\n'
                     f"Content-Type: application/octet-stream\r\n\r\n".encode() + f.read() + b"\r\n")
    data = b"".join(parts) + f"--{boundary}--\r\n".encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data,
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode() or "{}")
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                sleep(body.get("parameters", {}).get("retry_after") or 2 ** attempt)
                continue
            raise TelegramError(e.code, body.get("description", ""))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
            sleep(2 ** attempt)
