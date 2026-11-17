#!/usr/bin/env python3
"""Render the Neofetch-style profile card (neofetch/dark.svg + neofetch/light.svg).

Stats come from the public GitHub REST API. In GitHub Actions the workflow passes
GITHUB_TOKEN; locally you can pass --stats stats.json to render without network.
"""
import argparse
import datetime as dt
import html
import json
import os
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEO = ROOT / "neofetch"

THEMES = {
    "dark": dict(bg="#0d1117", bar="#161b22", border="#30363d", ascii="#c9d1d9",
                 key="#ffa657", value="#a5d6ff", dots="#484f58", title="#7ee787",
                 rule="#30363d", add="#3fb950", note="#8b949e"),
    "light": dict(bg="#ffffff", bar="#f6f8fa", border="#d0d7de", ascii="#24292f",
                  key="#953800", value="#0a3069", dots="#d0d7de", title="#116329",
                  rule="#d0d7de", add="#1a7f37", note="#57606a"),
}

FONT = 14          # px
CH = FONT * 0.6    # monospace advance width
LH = 20            # line height
RIGHT_COLS = 58    # width of the info column in characters
ART_CW, ART_LH = 6, 11   # braille portrait cell size in px (2x4 dots per cell)
BRAILLE_BITS = [(0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
                (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80)]
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, &apos;DejaVu Sans Mono&apos;, &apos;Liberation Mono&apos;, monospace"


def api(path, token):
    req = urllib.request.Request(f"https://api.github.com/{path}")
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_stats(user, token):
    u = api(f"users/{user}", token)
    repos, page = [], 1
    while True:
        batch = api(f"users/{user}/repos?type=owner&per_page=100&page={page}", token)
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"]]
    langs = Counter()
    for r in own:
        try:
            for k, v in api(f"repos/{user}/{r['name']}/languages", token).items():
                langs[k] += v
        except Exception:
            pass
    try:
        commits = api(f"search/commits?q=author:{user}&per_page=1", token)["total_count"]
    except Exception:
        commits = None
    return dict(
        created_at=u["created_at"],
        repos=len(repos),
        own_repos=len(own),
        stars=sum(r["stargazers_count"] for r in own),
        followers=u["followers"],
        commits=commits,
        languages=[k for k, _ in langs.most_common(4)],
    )


def age(created_at):
    start = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    today = dt.date.today()
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    y, m = divmod(months, 12)
    return f"{y} years, {m} months"


def fmt(n):
    return "n/a" if n is None else f"{n:,}"


def build_lines(profile, stats):
    sub = dict(github_age=age(stats["created_at"]),
               top_languages=", ".join(stats["languages"]) or "Python")
    lines = [("title", profile["title"])]
    lines.append(("rule", ""))
    for f in profile["fields"]:
        if len(f) == 1 or not f[0]:
            lines.append(("blank", ""))
        else:
            lines.append(("kv", (f[0], f[1].format(**sub))))
    lines.append(("blank", ""))
    lines.append(("section", "Contact"))
    for k, v in profile["contact"]:
        lines.append(("kv", (k, v)))
    lines.append(("blank", ""))
    lines.append(("section", "GitHub Stats"))
    lines.append(("pair", (("Repos", fmt(stats["repos"])), ("Commits", fmt(stats["commits"])))))
    return lines


def esc(s):
    return html.escape(s, quote=False)


def kv_segs(key, value, width, c):
    dots = max(2, width - len(key) - len(value) - 3)
    return [(key, c["key"], False), (f": {'.' * dots} ", c["dots"], False), (value, c["value"], False)]


def line_svg(x, y, segs):
    """One <text> per line with flat sibling <tspan>s (renders the same everywhere)."""
    parts = []
    for text, color, bold in segs:
        w = ' font-weight="bold"' if bold else ''
        parts.append(f'<tspan fill="{color}" font-family="{MONO}"{w}>{esc(text)}</tspan>')
    return f'<text x="{x}" y="{y}" font-family="{MONO}" xml:space="preserve">{"".join(parts)}</text>'


def render(theme, ascii_lines, lines, updated):
    c = THEMES[theme]
    pad = 8
    bar_h = 0
    art_cols = max(len(l) for l in ascii_lines)
    art_w = art_cols * ART_CW
    art_h = len(ascii_lines) * ART_LH
    info_h = (len(lines) - 1) * LH + FONT
    x_ascii = pad
    x_info = pad + art_w + 40
    width = int(x_info + RIGHT_COLS * CH * 1.03 + pad)
    body_h = max(art_h, info_h)
    height = int(bar_h + pad + body_h + pad)
    art_top = bar_h + pad + (body_h - art_h) / 2
    y0 = bar_h + pad + (body_h - info_h) / 2 + FONT

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="{MONO}" font-size="{FONT}px">']

    # Draw the braille portrait as real dots so it looks the same in every browser/font.
    dots = []
    for r, l in enumerate(ascii_lines):
        for col, ch in enumerate(l):
            code = ord(ch) - 0x2800
            if not 0 < code < 256:
                continue
            for dx, dy, bit in BRAILLE_BITS:
                if code & bit:
                    x = x_ascii + col * ART_CW + 1.5 + dx * 3
                    y = art_top + r * ART_LH + 1.5 + dy * 2.6
                    dots.append(f"M{x:g} {y:g}h0")
    out.append(f'<path d="{"".join(dots)}" stroke="{c["ascii"]}" stroke-width="1.7" '
               f'stroke-linecap="round" fill="none"/>')
    for i, (kind, data) in enumerate(lines):
        y = y0 + i * LH
        if kind == "title":
            user, _, host = data.partition("@")
            segs = [(user, c["title"], True), ("@", c["ascii"], True), (host, c["title"], True)]
        elif kind == "rule":
            segs = [("─" * RIGHT_COLS, c["rule"], False)]
        elif kind == "section":
            label = f"- {data} "
            segs = [(label, c["title"], True), ("─" * (RIGHT_COLS - len(label)), c["rule"], False)]
        elif kind == "kv":
            segs = kv_segs(data[0], data[1], RIGHT_COLS, c)
        elif kind == "pair":
            half = (RIGHT_COLS - 3) // 2
            (k1, v1), (k2, v2) = data
            segs = kv_segs(k1, v1, half, c) + [(" | ", c["dots"], False)] + kv_segs(k2, v2, half, c)
        else:
            continue
        out.append(line_svg(x_info, y, segs))
    out.append('</svg>')
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", help="read stats from this JSON file instead of the API")
    args = ap.parse_args()
    profile = json.loads((NEO / "profile.json").read_text())
    if args.stats:
        stats = json.loads(Path(args.stats).read_text())
    else:
        stats = fetch_stats(profile["username"], os.environ.get("GITHUB_TOKEN"))
    lines = build_lines(profile, stats)
    updated = dt.date.today().isoformat()
    for theme in THEMES:
        art = (NEO / f"ascii-{theme}.txt").read_text().rstrip("\n").split("\n")
        (NEO / f"{theme}.svg").write_text(render(theme, art, lines, updated))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
