#!/usr/bin/env python3
"""
Render the profile README's cards as animated SVGs into cards/.

Every card is a standalone SVG shown through <img>, so it can only use what GitHub
allows there: inline CSS animations, SMIL, and fonts embedded as data URIs (no JS,
no external requests). Fonts live in fonts/ (Instrument Serif, Geist, Geist Mono;
all SIL OFL).

Live numbers (contributions, repos, stars) come from the GitHub API. The token is
read from GITHUB_TOKEN / GH_TOKEN, or from `gh auth token` when run locally.

    python3 scripts/render_cards.py            # animated
    STATIC=1 python3 scripts/render_cards.py   # every animation at its end state

Run daily by .github/workflows/profile-cards.yml.
"""
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import OrderedDict
from html import escape

USER = os.environ.get("PROFILE_USER", "keshavop")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "cards")
FONTS = os.path.join(ROOT, "fonts")

# ---- content ----------------------------------------------------------------
ROLE = "SOFTWARE ENGINEER"
SITE = "keshavop.vercel.app"
PINNED = ["Streamy-Youtube-Clone", "CodeSync-IDE", "Food-Ordering-App"]
STACK = [
    ("I CODE IN", ["C", "C++", "Python", "Java", "Kotlin", "JavaScript"]),
    ("FRONTEND", ["HTML", "CSS", "Tailwind", "TypeScript", "React", "Redux", "Angular", "Figma"]),
    ("BACKEND", ["Node.js", "Express", "MongoDB", "MySQL", "Firebase", "AWS", "GCP"]),
    ("TOOLS", ["Git", "Linux", "Docker", "VS Code", "IntelliJ", "Android Studio"]),
]

# ---- design tokens ----------------------------------------------------------
PAPER = "#f4f2ef"
PAPER_DEEP = "#e4e0db"
INK = "#121212"
INK_SOFT = "#3a3a3c"
MUTED = "#6e6e73"
RULE = "#dcd8d2"
PINK = "#f72eb3"    # the accent from the old typing banner
VIOLET = "#6c3cff"
LIME = "#c8f03c"
W = 880  # full card width, GitHub's README column at 100%

SERIF = "'Instrument Serif', Georgia, serif"
SANS = "Geist, system-ui, -apple-system, sans-serif"
MONO = "'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace"

FONT_FILES = {
    "serif": ("Instrument Serif", "normal", 400, "serif-400.woff"),
    "serif-i": ("Instrument Serif", "italic", 400, "serif-italic.woff"),
    "sans": ("Geist", "normal", 400, "geist-400.woff"),
    "sans-b": ("Geist", "normal", 600, "geist-600.woff"),
    "mono": ("Geist Mono", "normal", 400, "geistmono-400.woff"),
}

ANIM = ".r,.f,.g,.p,.live,.n,.ti,.sl,.ro,.cur"
BASE_CSS = """
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes pop{0%{opacity:0;transform:scale(.3)}70%{opacity:1;transform:scale(1.15)}100%{opacity:1;transform:none}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes nudge{0%,100%{transform:none}50%{transform:translate(3px,-3px)}}
@keyframes tilein{0%{opacity:0;transform:translateY(80px) scale(.7) rotate(-6deg)}60%{opacity:1;transform:translateY(-8px) scale(1.03) rotate(1.5deg)}100%{opacity:1;transform:none}}
@keyframes slidein{from{opacity:0;transform:translateX(-22px)}to{opacity:1;transform:none}}
@keyframes roll{from{transform:translateY(60px)}to{transform:none}}
@keyframes sheen{0%{transform:translateX(-260px) skewX(-20deg)}22%,100%{transform:translateX(420px) skewX(-20deg)}}
.r{opacity:0;animation:rise .8s cubic-bezier(.2,.7,.2,1) both;transform-box:fill-box}
.f{opacity:0;animation:fade .7s ease-out both}
.g{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .8s cubic-bezier(.2,.7,.2,1) both}
.p{opacity:0;transform-box:fill-box;transform-origin:center;animation:pop .4s ease-out both}
.live{animation:pulse 1.6s ease-in-out infinite}
.cur{animation:blink 1s step-end infinite}
.n{transform-box:fill-box;animation:nudge 1.8s ease-in-out infinite}
.ti{opacity:0;transform-box:fill-box;transform-origin:50% 60%;animation:tilein 1s cubic-bezier(.2,.8,.2,1) both}
.sl{opacity:0;transform-box:fill-box;animation:slidein .6s cubic-bezier(.2,.7,.2,1) both}
.ro{transform-box:fill-box;animation:roll .8s cubic-bezier(.15,.8,.2,1) both}
.sh{animation:sheen 5s ease-in-out infinite}
"""
STILL = ANIM + "{animation:none!important;opacity:1!important;transform:none!important}.sh{display:none}"
BASE_CSS += "@media (prefers-reduced-motion: reduce){" + STILL + "}"

GAP = 12      # gap between cards, baked into the SVGs (GitHub's own spacing is uneven)
BOTTOM = 12   # bottom padding per row, matching GAP
THIRD = W / 3 - 8


# ---- helpers ----------------------------------------------------------------
def font_face(keys):
    out = []
    for k in keys:
        fam, style, weight, fn = FONT_FILES[k]
        with open(os.path.join(FONTS, fn), "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        out.append(
            f"@font-face{{font-family:'{fam}';font-style:{style};font-weight:{weight};"
            f"src:url(data:font/woff;base64,{b64}) format('woff')}}"
        )
    return "".join(out)


def svg(w, h, body, fonts, label, left=0, right=0, bottom=BOTTOM):
    """Card of w x h drawn at x=left inside a transparent canvas, padded so rows tile exactly."""
    if left:
        body = f'<g transform="translate({left:.3f} 0)">{body}</g>'
    w, h = w + left + right, h + bottom
    css = font_face(fonts) + BASE_CSS
    if os.environ.get("STATIC"):
        css += STILL
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.3f}" height="{h}" viewBox="0 0 {w:.3f} {h}" '
        f'role="img" aria-label="{escape(label)}"><title>{escape(label)}</title>'
        f"<style>{css}</style>{body}</svg>"
    )


def write(name, content):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w") as fh:
        fh.write(content)
    print(f"wrote cards/{name} ({len(content) // 1024} KB)")


def d(s):
    return f'style="animation-delay:{s:.2f}s"'


def wrap(text, n):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > n:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line] if line else lines


def text_lines(x, y, lines, lh, attrs):
    return "".join(
        f'<text x="{x}" y="{y + i * lh}" {attrs}>{escape(l)}</text>' for i, l in enumerate(lines)
    )


def count_up(num, word, x, y, attrs, begin, dur=1.1, frames=18):
    """Number counts up from 0 with SMIL <set> frames (works inside <img>), easing out."""
    m = re.match(r"([\d.,]+)(.*)", num)
    raw, suf = m.group(1).replace(",", ""), m.group(2)
    val = float(raw)
    dec = len(raw.split(".")[1]) if "." in raw else 0
    tail = f' <tspan font-style="italic">{escape(word)}</tspan>'
    if os.environ.get("STATIC"):
        return f'<text x="{x}" y="{y}" {attrs}>{escape(num)}{tail}</text>'
    out = []
    for i in range(frames + 1):
        e = 1 - (1 - i / frames) ** 3
        txt = num if i == frames else f"{val * e:,.{dec}f}{suf}"
        on = begin + dur * i / frames
        off = "" if i == frames else f'<set attributeName="opacity" to="0" begin="{begin + dur * (i + 1) / frames:.3f}s"/>'
        out.append(f'<text x="{x}" y="{y}" {attrs} opacity="0">{escape(txt)}{tail}'
                   f'<set attributeName="opacity" to="1" begin="{on:.3f}s"/>{off}</text>')
    return "".join(out)


# ---- data -------------------------------------------------------------------
def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sys.exit("no GITHUB_TOKEN / GH_TOKEN and `gh auth token` failed")


def api(path, query=None):
    url = "https://api.github.com/graphql" if query else f"https://api.github.com/{path}"
    data = json.dumps({"query": query}).encode() if query else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-cards",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if query and out.get("errors"):
        sys.exit(f"graphql error: {out['errors']}")
    return out


def load():
    q = """{ user(login: "%s") {
      contributionsCollection { contributionCalendar { totalContributions
        weeks { contributionDays { date contributionCount } } } } } }""" % USER
    cal = api(None, q)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [{"date": x["date"], "count": x["contributionCount"]}
            for w in cal["weeks"] for x in w["contributionDays"]]
    days.sort(key=lambda x: x["date"])

    repos, page = [], 1
    while True:
        batch = api(f"users/{USER}/repos?per_page=100&type=owner&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"]]

    # streaks within the calendar window; an unfinished today doesn't break the streak
    i = len(days) - 1
    if days[i]["count"] == 0:
        i -= 1
    cur = 0
    while i >= 0 and days[i]["count"] > 0:
        cur, i = cur + 1, i - 1
    longest = run = 0
    for x in days:
        run = run + 1 if x["count"] else 0
        longest = max(longest, run)

    monthly = OrderedDict()
    for x in days:
        monthly[x["date"][:7]] = monthly.get(x["date"][:7], 0) + x["count"]

    return {
        "days": days,
        "total": cal["totalContributions"],
        "current_streak": cur,
        "longest_streak": longest,
        "active_days": sum(1 for x in days if x["count"]),
        "best_day": max(x["count"] for x in days),
        "monthly": [{"month": k, "total": v} for k, v in monthly.items()][-12:],
        "repos": len(own),
        "stars": sum(r["stargazers_count"] for r in own),
        "by_name": {r["name"]: r for r in repos},
    }


# ---- 1 · hero ---------------------------------------------------------------
def hero():
    h = 400
    tx, ty, tw, th = 498, 44, 338, 312
    term = [
        ("$ whoami", MUTED),
        ("keshav, software engineer", "#f4f2ef"),
        ("", None),
        ("$ cat about.txt", MUTED),
        ("techie nerd, shipping since 2020", "#f4f2ef"),
        ("", None),
        ("$ cat fun_fact.txt", MUTED),
        ("if it's working, don't touch it.", PINK),
        ("", None),
        ("$ cat goal.txt", MUTED),
        ("hustle into the top 0.1%", LIME),
    ]
    lines = []
    for i, (t, c) in enumerate(term):
        if t:
            lines.append(
                f'<text class="f" style="animation-delay:{0.9 + i * 0.16:.2f}s;animation-duration:.25s" '
                f'x="{tx + 22}" y="{ty + 62 + i * 21}" font-family="{MONO}" font-size="13" fill="{c}" '
                f'xml:space="preserve">{escape(t)}</text>'
            )
    cy = ty + 62 + len(term) * 21
    lines.append(
        f'<g class="f" {d(0.9 + len(term) * 0.16)}><text x="{tx + 22}" y="{cy}" font-family="{MONO}" '
        f'font-size="13" fill="{MUTED}">$</text><rect class="cur" x="{tx + 36}" y="{cy - 11}" width="8" '
        f'height="14" fill="{PINK}"/></g>'
    )
    dots = "".join(
        f'<circle cx="{tx + 22 + i * 16}" cy="{ty + 22}" r="5" fill="{c}"/>'
        for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"])
    )
    body = f"""
<defs>
  <linearGradient id="shine" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="440" y2="0">
    <stop offset="0" stop-color="{PINK}"/><stop offset=".42" stop-color="{PINK}"/>
    <stop offset=".5" stop-color="{VIOLET}"/><stop offset=".58" stop-color="{PINK}"/>
    <stop offset="1" stop-color="{PINK}"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-440 0;440 0;440 0"
      keyTimes="0;.45;1" dur="7s" begin="1.6s" repeatCount="indefinite"/>
  </linearGradient>
</defs>
<rect width="{W}" height="{h}" rx="14" fill="{PAPER}"/>
<g class="f" {d(0)}>
  <rect class="live" x="48" y="49" width="8" height="8" rx="2" fill="{PINK}"/>
  <text x="66" y="57" font-family="{MONO}" font-size="12" letter-spacing="1" fill="{MUTED}">{ROLE}</text>
</g>
<text class="r" {d(0.15)} x="42" y="180" font-family="{SERIF}" font-size="128" letter-spacing="-2.5" fill="{INK}">Keshav</text>
<text class="r" {d(0.3)} x="46" y="246" font-family="{SERIF}" font-style="italic" font-size="52" letter-spacing="-.5" fill="url(#shine)">creating bugs since 2020</text>
<g class="r" {d(0.55)}>
  {text_lines(48, 292, ["Techie nerd who builds for the web,", "then ships it before it gets cold."], 26, f'font-family="{SANS}" font-size="18" fill="{INK_SOFT}"')}
</g>
<g class="f" {d(0.8)}>
  <text x="48" y="360" font-family="{MONO}" font-size="13" fill="{INK}">{SITE}</text>
  <text class="n" x="{48 + len(SITE) * 7.9 + 6:.0f}" y="360" font-family="{MONO}" font-size="13" fill="{PINK}">&#8599;</text>
</g>
<g class="sl" {d(0.6)}>
  <rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="12" fill="{INK}"/>
  {dots}
  <text x="{tx + tw - 18}" y="{ty + 26}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{MUTED}">~/keshavop</text>
</g>
{''.join(lines)}
"""
    write("hero.svg", svg(W, h, body, ["serif", "serif-i", "sans", "mono"],
                          "Keshav. Software engineer, creating bugs since 2020."))


# ---- 2 · tiles --------------------------------------------------------------
TILE_H = 200


def tile(name, label, color, on, num, word, blurb, delay, pos):
    blurb_svg = "".join(
        f'<text class="r" {d(delay + 0.75 + i * 0.1)} x="24" y="{146 + i * 20}" font-family="{SANS}" '
        f'font-size="14" fill="{on}" opacity=".92">{escape(l)}</text>'
        for i, l in enumerate(wrap(blurb, 34))
    )
    body = f"""
<defs>
  <clipPath id="card"><rect width="{THIRD}" height="{TILE_H}" rx="14"/></clipPath>
  <clipPath id="slot"><rect x="0" y="62" width="{THIRD}" height="62"/></clipPath>
  <linearGradient id="gl" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>
    <stop offset=".5" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<g class="ti" {d(delay)}>
  <g clip-path="url(#card)">
    <rect width="{THIRD}" height="{TILE_H}" fill="{color}"/>
    <rect class="sh" style="animation-delay:{delay + 1.4:.2f}s" x="0" y="-20" width="90" height="{TILE_H + 40}" fill="url(#gl)" transform="translate(-260 0)"/>
  </g>
  <text class="sl" {d(delay + 0.35)} x="24" y="38" font-family="{MONO}" font-size="12" letter-spacing="1.2" fill="{on}">{label}</text>
  <g clip-path="url(#slot)"><g class="ro" {d(delay + 0.45)}>
    {count_up(num, word, 22, 110, f'font-family="{SERIF}" font-size="46" fill="{on}"', delay + 0.45)}
  </g></g>
  {blurb_svg}
</g>
"""
    write(f"{name}.svg", svg(THIRD, TILE_H, body, ["serif", "serif-i", "sans", "mono"],
                             f"{label}: {num} {word}. {blurb}", left=4 * pos, right=8 - 4 * pos))


# ---- 3 · activity -----------------------------------------------------------
def activity(data):
    h = 340
    monthly = data["monthly"]
    best = max(monthly[:-1] or monthly, key=lambda m: m["total"])
    top = max(best["total"], 1)
    x0, x1, base, maxh, gap = 40, 600, 292, 140, 10
    bw = (x1 - x0 - gap * (len(monthly) - 1)) / len(monthly)
    bars = []
    for i, m in enumerate(monthly):
        partial = i == len(monthly) - 1
        bh = max(4, round(min(m["total"], top) / top * maxh))
        x = x0 + i * (bw + gap)
        fill = PINK if m is best else ("#cbc6c0" if partial else INK)
        label = datetime.date.fromisoformat(m["month"] + "-01").strftime("%b")
        dl = 2.2 + i * 0.07
        bars.append(
            f'<rect class="g" style="animation-delay:{dl:.2f}s" x="{x:.1f}" y="{base - bh}" '
            f'width="{bw:.1f}" height="{bh}" rx="4" fill="{fill}"><title>{label}: {m["total"]:,}</title></rect>'
            f'<text class="f" style="animation-delay:{dl:.2f}s" x="{x + bw / 2:.1f}" y="{base + 22}" '
            f'text-anchor="middle" font-family="{MONO}" font-size="11" fill="{MUTED}">{label}</text>'
        )
        if m is best:
            bars.append(
                f'<text class="p" style="animation-delay:3.2s" x="{x + bw / 2:.1f}" y="{base - bh - 10}" '
                f'text-anchor="middle" font-family="{MONO}" font-size="11" fill="{PINK}">{m["total"]:,}</text>'
            )
    cs, ls = data["current_streak"], data["longest_streak"]
    stats = [
        (f'{cs} <tspan font-style="italic">day{"s" if cs != 1 else ""}</tspan>',
         "current streak, and the longest" if cs >= ls and cs else f"current streak, longest {ls}"),
        (f'{data["active_days"]}<tspan fill="#8e8e93"> / {len(data["days"])}</tspan>', "days with a commit"),
        (f'{data["best_day"]}', "on the busiest day"),
    ]
    side = []
    for i, (big, small) in enumerate(stats):
        y = 104 + i * 92
        side.append(
            f'<g class="r" {d(2.6 + i * 0.15)}>'
            f'<text x="650" y="{y}" font-family="{SERIF}" font-size="40" fill="{INK}">{big}</text>'
            f'<text x="650" y="{y + 24}" font-family="{SANS}" font-size="13" fill="{MUTED}">{small}</text></g>'
        )
        if i < 2:
            side.append(f'<rect class="f" {d(2.6)} x="650" y="{y + 44}" width="190" height="1" fill="{RULE}"/>')
    body = f"""
<rect width="{W}" height="{h}" rx="14" fill="{PAPER}"/>
<text class="f" {d(1.9)} x="40" y="58" font-family="{MONO}" font-size="12" letter-spacing="1" fill="{MUTED}">THE LAST 12 MONTHS ON GITHUB</text>
<text class="r" {d(2.0)} x="38" y="114" font-family="{SERIF}" font-size="52" fill="{INK}">{data["total"]:,} <tspan font-style="italic">contributions</tspan></text>
{''.join(bars)}
{''.join(side)}
"""
    write("activity.svg", svg(W, h, body, ["serif", "serif-i", "sans", "mono"],
                              f'{data["total"]:,} contributions in the last year, {cs}-day streak'))


# ---- 4 · heatmap ------------------------------------------------------------
SHADES = [PAPER_DEEP, "#fcd0ec", "#f9a3dc", "#f86bc9", PINK, "#b8127f"]


def level_for(c):
    return 0 if c == 0 else 1 if c <= 2 else 2 if c <= 5 else 3 if c <= 10 else 4 if c <= 20 else 5


def heatmap(data):
    days = data["days"]
    first = datetime.date.fromisoformat(days[0]["date"])
    lead = (first.weekday() + 1) % 7  # sunday = 0
    cell, step, gx, gy = 12, 15, 44, 96
    cells, months, seen = [], [], set()
    for i, day in enumerate(days):
        col, row = divmod(i + lead, 7)
        date = datetime.date.fromisoformat(day["date"])
        if date.day <= 7 and (date.year, date.month) not in seen and row == 0:
            seen.add((date.year, date.month))
            months.append((col, date.strftime("%b")))
        c = day["count"]
        cells.append(
            f'<rect class="p" style="animation-delay:{1.0 + col * 0.03 + row * 0.02:.2f}s" x="{gx + col * step}" '
            f'y="{gy + row * step}" width="{cell}" height="{cell}" rx="3" fill="{SHADES[level_for(c)]}">'
            f'<title>{day["date"]}: {c} contribution{"s" if c != 1 else ""}</title></rect>'
        )
    ncols = (len(days) + lead + 6) // 7
    right = gx + ncols * step - 3
    labels = "".join(
        f'<text x="{gx + col * step}" y="{gy + 7 * step + 16}" font-family="{MONO}" font-size="11" fill="{MUTED}">{m}</text>'
        for col, m in months
    )
    legend_x = right - len(SHADES) * 14 - 30
    legend = "".join(
        f'<rect x="{legend_x + i * 14}" y="{gy + 7 * step + 26}" width="11" height="11" rx="2.5" fill="{c}"/>'
        for i, c in enumerate(SHADES)
    )
    h = gy + 7 * step + 64
    body = f"""
<rect width="{W}" height="{h}" rx="14" fill="{PAPER}"/>
<text class="r" {d(0.8)} x="42" y="62" font-family="{SERIF}" font-size="34" fill="{INK}">Every day, <tspan font-style="italic" fill="{PINK}">in pink</tspan></text>
<text class="f" {d(0.8)} x="{right}" y="60" text-anchor="end" font-family="{MONO}" font-size="12" letter-spacing="1" fill="{MUTED}">REFRESHED DAILY</text>
{''.join(cells)}
<g class="f" {d(2.4)}>{labels}
<text x="{legend_x - 8}" y="{gy + 7 * step + 36}" text-anchor="end" font-family="{MONO}" font-size="11" fill="{MUTED}">less</text>
{legend}
<text x="{legend_x + len(SHADES) * 14 + 2}" y="{gy + 7 * step + 36}" font-family="{MONO}" font-size="11" fill="{MUTED}">more</text></g>
"""
    write("heatmap.svg", svg(W, h, body, ["serif", "serif-i", "mono"],
                             f'Contribution graph: {data["total"]:,} contributions in the last year'))


# ---- 5 · stack --------------------------------------------------------------
def stack():
    row_h, top = 58, 96
    h = top + (len(STACK) - 1) * row_h + 40
    colors = [PINK, VIOLET, LIME, INK]
    rows, k = [], 0
    for r, (label, items) in enumerate(STACK):
        y = top + r * row_h
        rows.append(
            f'<g class="sl" {d(0.4 + r * 0.12)}><rect x="40" y="{y - 9}" width="8" height="8" rx="2" fill="{colors[r]}"/>'
            f'<text x="56" y="{y}" font-family="{MONO}" font-size="11" letter-spacing="1" fill="{MUTED}">{label}</text></g>'
        )
        x = 196
        for item in items:
            cw = len(item) * 7.6 + 24
            rows.append(
                f'<g class="p" {d(0.6 + k * 0.035)}><rect x="{x:.1f}" y="{y - 21}" width="{cw:.1f}" height="30" rx="15" '
                f'fill="#fff" stroke="{RULE}"/><text x="{x + cw / 2:.1f}" y="{y - 1}" text-anchor="middle" '
                f'font-family="{MONO}" font-size="12.5" fill="{INK}">{escape(item)}</text></g>'
            )
            x += cw + 8
            k += 1
    body = f"""
<rect width="{W}" height="{h}" rx="14" fill="{PAPER}"/>
<text class="r" {d(0.1)} x="40" y="58" font-family="{SERIF}" font-size="34" fill="{INK}">The <tspan font-style="italic">toolbox</tspan></text>
{''.join(rows)}
"""
    label = "; ".join(f"{l.title()}: {', '.join(i)}" for l, i in STACK)
    write("stack.svg", svg(W, h, body, ["serif", "serif-i", "mono"], f"Skills. {label}"))


# ---- 6 · repos + section titles ---------------------------------------------
REPO_H = 176
LANG_COLORS = [PINK, VIOLET, LIME]


def repo_card(i, repo):
    name = repo["name"]
    desc = repo.get("description") or ""
    if desc.startswith("http"):
        desc = "Order food online, live on GitHub Pages."
    meta = f'{repo.get("language") or "Code"}  ·  ★ {repo["stargazers_count"]}'
    lines = wrap(desc, 34)[:3]
    if len(wrap(desc, 34)) > 3:
        lines[-1] = lines[-1].rstrip(".,") + "…"
    body = f"""
<rect width="{THIRD}" height="{REPO_H}" rx="14" fill="{PAPER}"/>
<g class="r" {d(0.3 + i * 0.12)}>
  <rect x="24" y="30" width="8" height="8" rx="2" fill="{LANG_COLORS[i % 3]}"/>
  <text x="40" y="39" font-family="{SANS}" font-weight="600" font-size="17" fill="{INK}">{escape(name)}</text>
  {text_lines(24, 72, lines, 21, f'font-family="{SANS}" font-size="14" fill="{INK_SOFT}"')}
  <text x="24" y="{REPO_H - 24}" font-family="{MONO}" font-size="12" fill="{MUTED}">{escape(meta)}</text>
</g>
"""
    write(f"repo-{i + 1}.svg", svg(THIRD, REPO_H, body, ["sans", "sans-b", "mono"], f"{name}: {desc}",
                                   left=4 * i, right=8 - 4 * i))


def section_title(slug, text, italic):
    for theme, fg in (("light", INK), ("dark", "#e6edf3")):
        body = (
            f'<text class="r" {d(0.2)} x="2" y="46" font-family="{SERIF}" font-size="34" fill="{fg}">{escape(text)} '
            f'<tspan font-style="italic">{escape(italic)}</tspan></text>'
        )
        write(f"title-{slug}-{theme}.svg", svg(W, 64, body, ["serif", "serif-i"], f"{text} {italic}", bottom=0))


if __name__ == "__main__":
    TOKEN = token()
    data = load()
    hero()
    tile("build", "BUILD", PINK, "#ffffff", f'{data["repos"]}', "repos",
         "Public projects since 2020: clones, IDEs, DSA and everything between.", 0.9, 0)
    tile("ship", "SHIP", VIOLET, "#ffffff", f'{data["stars"]}', "stars",
         "Earned by open source work, led by Streamy, the YouTube clone.", 1.1, 1)
    tile("goal", "GOAL", LIME, INK, "0.1%", "club",
         "Hustling every single day to get into the top 0.1%.", 1.3, 2)
    activity(data)
    heatmap(data)
    stack()
    section_title("coding", "What I'm", "coding")
    section_title("koi", "Meet my", "koi")
    section_title("snake", "The snake that", "eats my commits")
    for i, name in enumerate(PINNED):
        repo_card(i, data["by_name"][name])
