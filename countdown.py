"""Countdown fissato: un solo messaggio, modificato sul posto. Modalità "time" (data assoluta) o "members"."""
import datetime


def remaining_parts(target, now):
    secs = max(0, int((target - now).total_seconds()))
    return secs // 86400, secs % 86400 // 3600, secs % 3600 // 60, secs


def bar(count, goal):
    done = min(10, max(count * 10 // goal, 1 if count else 0))
    return f"{'🟧' * done}{'⬜' * (10 - done)} {count}/{goal}"


def render(cfg, now, count):
    c = cfg["countdown"]
    if c["mode"] == "time" and c.get("target"):
        target = datetime.datetime.fromisoformat(c["target"])  # con fuso orario, es. 2026-11-01T20:00:00+01:00
        d, h, m, secs = remaining_parts(target, now)
        if secs == 0:
            return c["text_done_time"], True
        return c["text_time"].format(d=d, h=f"{h:02d}", m=f"{m:02d}", count=count), False
    goal = c["goal"]
    if count >= goal:
        return c["text_done_members"].format(bar=bar(count, goal), goal=goal), True
    return c["text_members"].format(bar=bar(count, goal), left=goal - count, goal=goal), False
