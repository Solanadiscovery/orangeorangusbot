"""Telegram Bot API: chiamate con retry, backoff e rispetto dei limiti (429 retry_after)."""
import json, os, time, urllib.error, urllib.request


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
