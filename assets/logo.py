"""Draw Tiresias's logo: frosted glass, and the one thing you are shown through it.

    python assets/logo.py        (writes the SVGs next to this file)

Tiresias is the seer of Thebes who knew the truth without seeing it. The mark is the crystal of
Glass, the language Tiresias is built on, with its spokes kept and its body filled with rows of
cells: a committed dataset. The rows show for a moment and then frost over, because they are
never revealed. In a clear window at the centre stands a sigma, the aggregate, with a diamond
under it for the proof that it is true. Ink, line weight and the diamonds follow the house style
of github.com/EgorKhaklin; the wordmark is set in Cinzel capitals, kept as outlines
(cinzel-caps.json, SIL Open Font License 1.1) so it renders the same everywhere.

GitHub serves these through an img tag, so the animation lives inside each SVG: it plays once,
uses opacity, transforms and stroke drawing only, and a reduced-motion rule shows the finished
frame.

Writes: tiresias-light.svg and tiresias-dark.svg (the lockup for the README header), and
tiresias-mark-light.svg and tiresias-mark-dark.svg (the mark alone, square).
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPS = json.loads((HERE / "cinzel-caps.json").read_text())
THEMES = {"light": ("#1F2328", "#59636E"), "dark": ("#E6EDF3", "#9198A1")}
NAME, SUBTITLE = "TIRESIAS", "VERIFIABLE PRIVATE ANALYTICS"

# the mark, in its own 240 x 240 box: Glass's hexagon standing on a corner, a window inside it
C, R, WIN = 120.0, 104.0, 46.0
ROW_PITCH, ROW_TOP, ROW_BOTTOM = 9.0, 22.0, 218.0
FROST = .2                       # the rows' opacity once frosted


def hexagon(r):
    return [(C + r * math.cos(math.radians(60 * k - 90)), C + r * math.sin(math.radians(60 * k - 90)))
            for k in range(6)]


V, W = hexagon(R), hexagon(WIN)


def f(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


def poly(pts):
    return "M" + "L".join("%s %s" % (f(x), f(y)) for x, y in pts) + "Z"


def diamond(cx, cy, r):
    return ('<rect x="%s" y="%s" width="%s" height="%s" transform="rotate(45 %s %s)"/>'
            % (f(cx - r), f(cy - r), f(2 * r), f(2 * r), f(cx), f(cy)))


def text_run(label, cap, track_em, x0, base):
    """Cinzel capitals from x0 on a baseline: (svg, width)."""
    s = cap / CAPS["cap"]
    track = track_em * CAPS["upm"] * s
    out, x = [], 0.0
    for ch in label:
        if ch == " ":
            x += CAPS["space"] * s + track
            continue
        g = CAPS["glyphs"][ch]
        out.append('<path transform="translate(%s %s) scale(%s)" d="%s"/>'
                   % (f(x0 + x), f(base), ("%.5f" % s).rstrip("0"), g["d"]))
        x += g["advance"] * s + track
    return "".join(out), x - track


def rows():
    """The dataset: rows of cells of uneven width, the same every run (a fixed linear
    congruential sequence), one path per row so each can show and frost in turn."""
    out, state, i = [], 20261007, 0
    y = ROW_TOP
    while y <= ROW_BOTTOM + .01:
        state = (state * 1103515245 + 12345) % 2 ** 31
        x, d = -4.0 - state % 11, []
        while x < 244:
            state = (state * 1103515245 + 12345) % 2 ** 31
            w = 7 + state % 20
            d.append("M%s %sH%s" % (f(x), f(y), f(x + w)))
            x += w + 4.5
        out.append('<path class="row" style="animation-delay:%ss" d="%s"/>' % (f(.2 + .035 * i), "".join(d)))
        y += ROW_PITCH
        i += 1
    return "".join(out)


def sigma(cx, cy, w, h):
    """A sigma in line art, with a short serif at each end of its bars."""
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    return ("M%s %sV%sH%sL%s %sL%s %sH%sV%s"
            % (f(x1), f(y0 + 6), f(y0), f(x0), f(x0 + .5 * w), f(cy), f(x0), f(y1), f(x1), f(y1 - 6)))


STYLE = (".draw{stroke-dasharray:1 2;stroke-dashoffset:1.01;animation:draw 1.1s cubic-bezier(.45,0,.2,1) .1s 1 both}"
         ".win{stroke-dasharray:1 2;stroke-dashoffset:1.01;animation:draw .9s cubic-bezier(.45,0,.2,1) 1.25s 1 both}"
         ".sig{stroke-dasharray:1 2;stroke-dashoffset:1.01;animation:draw .8s cubic-bezier(.3,0,.2,1) 1.6s 1 both}"
         ".row{opacity:%s;animation:row 1.9s ease-out .2s 1 both}"
         ".spoke{opacity:0;animation:spoke .8s ease-out 1.1s 1 both}"
         ".gem{opacity:0;animation:fade .5s ease-out 2.2s 1 both}"
         ".word{opacity:0;animation:fade 1s ease-out 1.2s 1 both}"
         ".glint{opacity:0;animation:glint 1.1s cubic-bezier(.4,0,.2,1) 2.45s 1 both}"
         "@keyframes draw{from{stroke-dashoffset:1.01}to{stroke-dashoffset:0}}"
         "@keyframes fade{from{opacity:0}to{opacity:1}}"
         "@keyframes row{0%%{opacity:0}40%%{opacity:.62}100%%{opacity:%s}}"
         "@keyframes spoke{from{opacity:0}to{opacity:.6}}"
         "@keyframes glint{0%%{opacity:0;transform:translateX(0px) skewX(-20deg)}20%%{opacity:1}80%%{opacity:1}"
         "100%%{opacity:0;transform:translateX(190px) skewX(-20deg)}}"
         "@media (prefers-reduced-motion: reduce){.draw,.win,.sig{animation:none;stroke-dashoffset:0}"
         ".gem,.word{animation:none;opacity:1}.row{animation:none}.spoke{animation:none;opacity:.6}"
         ".glint{animation:none;opacity:0}}") % (f(FROST), f(FROST))


def mark_svg(ink, ox, oy, k, uid):
    """The mark at (ox, oy), scale k. uid keeps ids unique when several are inlined."""
    spokes = "".join("M%s %sL%s %s" % (f(a[0]), f(a[1]), f(b[0]), f(b[1])) for a, b in zip(W, V))
    # The rows fill the body between the outline and the window, kept clear of both.
    body = poly(hexagon(R - 5)) + poly(hexagon(WIN + 5))
    return f"""<g transform="translate({f(ox)} {f(oy)}) scale({f(k)})">
<defs>
<clipPath id="body{uid}"><path clip-rule="evenodd" d="{body}"/></clipPath>
<clipPath id="win{uid}"><path d="{poly(W)}"/></clipPath>
<linearGradient id="sheen{uid}" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="{ink}" stop-opacity="0"/><stop offset=".5" stop-color="{ink}" stop-opacity=".22"/><stop offset="1" stop-color="{ink}" stop-opacity="0"/></linearGradient>
</defs>
<g clip-path="url(#body{uid})" fill="none" stroke="{ink}" stroke-width="1.5" stroke-linecap="butt">{rows()}</g>
<g class="spoke" fill="none" stroke="{ink}" stroke-width="1.1" stroke-linecap="round"><path d="{spokes}"/></g>
<g fill="none" stroke="{ink}" stroke-linecap="round" stroke-linejoin="round">
<path class="draw" pathLength="1" stroke-width="2.1" d="{poly(V)}"/>
<path class="win" pathLength="1" stroke-width="1.4" d="{poly(W)}"/>
<path class="sig" pathLength="1" stroke-width="2.4" stroke-linecap="square" stroke-linejoin="miter" d="{sigma(C, C - 5, 34, 42)}"/>
</g>
<g class="gem" fill="{ink}">{diamond(C, C + 29, 3.4)}</g>
<g clip-path="url(#win{uid})"><rect class="glint" x="{f(C - WIN - 40)}" y="{f(C - WIN)}" width="34" height="{f(2 * WIN)}" fill="url(#sheen{uid})"/></g>
</g>"""


def lockup(theme):
    ink, muted = THEMES[theme]
    Wd, H = 1200, 360
    k = 1.1
    name_cap, name_track = 66, .2
    sub_cap, sub_track = 14, .3
    _, nw = text_run(NAME, name_cap, name_track, 0, 0)
    _, sw = text_run(SUBTITLE, sub_cap, sub_track, 0, 0)
    bw = max(nw, sw)
    hw = 2 * R * math.sin(math.radians(60)) * k   # the hexagon's own width, for optical centring
    gap = 60
    hx = (Wd - (hw + gap + bw)) / 2
    tx = hx + hw + gap
    name, _ = text_run(NAME, name_cap, name_track, tx + (bw - nw) / 2, 189)
    sub, _ = text_run(SUBTITLE, sub_cap, sub_track, tx + (bw - sw) / 2, 239)
    rule_y = 213
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {Wd} {H}" width="{Wd}" height="{H}" role="img" aria-labelledby="t">
<title id="t">Tiresias: verifiable private analytics</title>
<style>{STYLE}</style>
{mark_svg(ink, hx - (C - hw / k / 2) * k, H / 2 - C * k, k, theme)}
<g class="word" fill="{ink}">{name}</g>
<g class="word" fill="{muted}">{sub}</g>
<g class="word" stroke="{muted}" stroke-width="1.1"><path d="M{f(tx)} {rule_y}H{f(tx + bw / 2 - 12)}M{f(tx + bw / 2 + 12)} {rule_y}H{f(tx + bw)}"/></g>
<g class="word" fill="{muted}">{diamond(tx + bw / 2, rule_y, 3.2)}</g>
</svg>
""", nw, sw


def mark(theme):
    ink, _ = THEMES[theme]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 280" width="280" height="280" role="img" aria-labelledby="t">
<title id="t">Tiresias</title>
<style>{STYLE}</style>
{mark_svg(ink, 20, 20, 1.0, "m" + theme)}
</svg>
"""


def still(svg):
    """The finished frame without animation, for web pages: the <style> is gone, so the SVG
    renders the same under any Content-Security-Policy, and the one-time glint is dropped."""
    import re
    svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.S)
    svg = re.sub(r'<rect class="glint"[^>]*/>', "", svg)
    svg = svg.replace('class="row"', 'opacity="0.2"').replace('class="spoke"', 'opacity="0.6"')
    return re.sub(r' class="(draw|win|sig|gem|word)"', "", svg)


def main():
    web = HERE.parent / "tiresias" / "web" / "static"
    for theme in THEMES:
        svg, nw, sw = lockup(theme)
        (HERE / f"tiresias-{theme}.svg").write_text(svg)
        (web / f"tiresias-{theme}.svg").write_text(still(svg))
        (HERE / f"tiresias-mark-{theme}.svg").write_text(mark(theme))
        print("%s: name %.0f px, subtitle %.0f px" % (theme, nw, sw))


if __name__ == "__main__":
    main()
