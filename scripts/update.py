"""Refresh the dynamic parts of the profile README and redraw the stats cards.

Run by .github/workflows/refresh.yml once a day. Standard library only.

    python3 scripts/update.py

Needs GITHUB_TOKEN in the environment for the GraphQL API.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

USERNAME = "coleRodneyMigisha"
BIRTHDAY = date(2004, 5, 27)
TZ = ZoneInfo("Africa/Kampala")

TOP_LANGUAGES = 6
# Exported reports (HTML, TeX) are generated documents, not code I wrote.
IGNORED_LANGUAGES = {"HTML", "TeX"}
# Notebooks are Python; counting them as such keeps the chart honest.
LANGUAGE_ALIASES = {"Jupyter Notebook": "Python"}
IGNORED_REPOS = {USERNAME}
RECENT_REPOS = 4

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ASSETS = ROOT / "assets"

# One palette for every graphic: GitHub's own neutrals plus a single blue.
THEMES = {
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "text": "#1f2328",
        "muted": "#59636e",
        "track": "#eaeef2",
        "accent": ["#0969da", "#2f81e4", "#5598e8", "#79aeec", "#98c0ef", "#b3d0f2", "#c9ddf4"],
    },
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "text": "#e6edf3",
        "muted": "#9198a1",
        "track": "#21262d",
        "accent": ["#4493f8", "#3b80dc", "#346fc1", "#2e5fa6", "#29528d", "#254677", "#213c64"],
    },
}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"


# ---------------------------------------------------------------- GitHub API

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description url pushedAt isFork isArchived
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def fetch_github() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set.")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USERNAME}}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{USERNAME}-profile-refresh",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        sys.exit(f"GitHub API error: {payload['errors']}")
    return payload["data"]["user"]


def summarise(user: dict, today: date) -> dict:
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    counts = {d["date"]: d["contributionCount"] for d in days}

    # A streak survives until the end of today, so start from yesterday if today is empty.
    streak, cursor = 0, today
    if counts.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    while counts.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)

    weekly = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in calendar["weeks"]]

    repos = [
        r for r in user["repositories"]["nodes"]
        if not r["isFork"] and r["name"] not in IGNORED_REPOS
    ]
    # Every repo gets an equal vote, split by its own language mix, so one
    # huge repo cannot drown out the rest.
    languages: dict[str, float] = {}
    for repo in repos:
        sizes: dict[str, int] = {}
        for edge in repo["languages"]["edges"]:
            name = LANGUAGE_ALIASES.get(edge["node"]["name"], edge["node"]["name"])
            if name not in IGNORED_LANGUAGES:
                sizes[name] = sizes.get(name, 0) + edge["size"]
        total = sum(sizes.values())
        for name, size in sizes.items():
            languages[name] = languages.get(name, 0) + size / total

    return {
        "contributions": calendar["totalContributions"],
        "streak": streak,
        "repos": user["repositories"]["totalCount"],
        "active_days": sum(1 for c in counts.values() if c > 0),
        "weekly": weekly,
        "languages": sorted(languages.items(), key=lambda kv: kv[1], reverse=True),
        "recent": [r for r in repos if not r["isArchived"]][:RECENT_REPOS],
    }


# ------------------------------------------------------------ SVG rendering

def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def svg_frame(width: int, height: int, theme: dict, title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        f"<title>{esc(title)}</title>"
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" '
        f'fill="{theme["bg"]}" stroke="{theme["border"]}"/>'
        f'<g font-family="{esc(FONT)}">{body}</g></svg>'
    )


def stats_svg(stats: dict, theme: dict) -> str:
    width, height, pad = 840, 236, 28
    metrics = [
        (f"{stats['contributions']:,}", "Contributions, past year"),
        (f"{stats['streak']}", "Day streak"),
        (f"{stats['active_days']}", "Active days, past year"),
        (f"{stats['repos']}", "Public repositories"),
    ]
    column = (width - 2 * pad) / len(metrics)
    body = []
    for i, (value, label) in enumerate(metrics):
        x = pad + i * column
        body.append(
            f'<text x="{x:.1f}" y="{pad + 30}" font-size="30" font-weight="600" '
            f'fill="{theme["text"]}">{esc(value)}</text>'
            f'<text x="{x:.1f}" y="{pad + 54}" font-size="13" fill="{theme["muted"]}">{esc(label)}</text>'
        )

    chart_top, chart_bottom = 122, height - pad
    body.append(
        f'<text x="{pad}" y="{chart_top - 10}" font-size="12" fill="{theme["muted"]}">'
        "Weekly contributions, last 12 months</text>"
    )
    weekly = stats["weekly"] or [0]
    peak = max(weekly) or 1
    slot = (width - 2 * pad) / len(weekly)
    bar = max(slot - 3, 2)
    span = chart_bottom - chart_top
    for i, count in enumerate(weekly):
        h = max(span * count / peak, 2)
        colour = theme["accent"][0] if count else theme["track"]
        body.append(
            f'<rect x="{pad + i * slot:.1f}" y="{chart_bottom - h:.1f}" width="{bar:.1f}" '
            f'height="{h:.1f}" rx="1.5" fill="{colour}"/>'
        )
    return svg_frame(width, height, theme, "GitHub activity", "".join(body))


def languages_svg(stats: dict, theme: dict) -> str:
    width, height, pad = 840, 128, 28
    ranked = stats["languages"]
    total = sum(size for _, size in ranked) or 1
    top = [(n, size) for n, size in ranked[:TOP_LANGUAGES] if size / total >= 0.005]
    rest = total - sum(size for _, size in top)
    if rest / total >= 0.005:
        top.append(("Other", rest))

    body = [
        f'<text x="{pad}" y="{pad + 8}" font-size="12" fill="{theme["muted"]}">'
        "Languages across public repositories, each repo weighted equally</text>"
    ]
    bar_y, bar_w, x = pad + 22, width - 2 * pad, float(pad)
    body.append(f'<clipPath id="bar"><rect x="{pad}" y="{bar_y}" width="{bar_w}" height="10" rx="5"/></clipPath>')
    segments = []
    for i, (_, size) in enumerate(top):
        w = bar_w * size / total
        segments.append(
            f'<rect x="{x:.2f}" y="{bar_y}" width="{w + 0.5:.2f}" height="10" '
            f'fill="{theme["accent"][min(i, len(theme["accent"]) - 1)]}"/>'
        )
        x += w
    body.append(f'<g clip-path="url(#bar)">{"".join(segments)}</g>')

    per_row = 4
    column = bar_w / per_row
    for i, (name, size) in enumerate(top):
        cx = pad + (i % per_row) * column
        cy = bar_y + 40 + (i // per_row) * 26
        share = 100 * size / total
        body.append(
            f'<circle cx="{cx + 5:.1f}" cy="{cy - 4}" r="5" '
            f'fill="{theme["accent"][min(i, len(theme["accent"]) - 1)]}"/>'
            f'<text x="{cx + 16:.1f}" y="{cy}" font-size="13" fill="{theme["text"]}">{esc(name)} '
            f'<tspan fill="{theme["muted"]}">{share:.1f}%</tspan></text>'
        )
    return svg_frame(width, height, theme, "Most used languages", "".join(body))


# ------------------------------------------------------------------- README

def recent_block(stats: dict) -> str:
    rows = []
    for repo in stats["recent"]:
        pushed = datetime.fromisoformat(repo["pushedAt"].replace("Z", "+00:00")).astimezone(TZ)
        about = repo.get("description") or ""
        about = f" · {about.replace('|', '/').strip()}" if about else ""
        rows.append(f"- [`{repo['name']}`]({repo['url']}){about} <sub>{pushed:%-d %b %Y}</sub>")
    return "\n".join(rows)


def age_on(today: date) -> int:
    return today.year - BIRTHDAY.year - ((today.month, today.day) < (BIRTHDAY.month, BIRTHDAY.day))


def replace_block(text: str, name: str, content: str, inline: bool = False) -> str:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        sys.exit(f"README is missing the {name} markers.")
    joined = f"{start}{content}{end}" if inline else f"{start}\n{content}\n{end}"
    return pattern.sub(lambda _: joined, text)


def main() -> None:
    now = datetime.now(TZ)
    today = now.date()
    stats = summarise(fetch_github(), today)

    ASSETS.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        (ASSETS / f"stats-{name}.svg").write_text(stats_svg(stats, theme), encoding="utf-8")
        (ASSETS / f"languages-{name}.svg").write_text(languages_svg(stats, theme), encoding="utf-8")

    text = README.read_text(encoding="utf-8")
    text = replace_block(text, "age", str(age_on(today)), inline=True)
    text = replace_block(text, "recent", recent_block(stats))
    text = replace_block(text, "updated", f"{today:%-d %B %Y}", inline=True)
    README.write_text(text, encoding="utf-8")
    print(f"Refreshed: {stats['contributions']} contributions, {stats['repos']} repos, streak {stats['streak']}.")


if __name__ == "__main__":
    main()
