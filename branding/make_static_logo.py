#!/usr/bin/env python3
"""
Make the PEBBL logo's static files from its generator, pebbl_core.js (version 7, signed off by HLU on
2026-10-31), with "pebbl" converted to outlines, so the files need no font to print or display.

    annotate_env\\Scripts\\python.exe branding\\make_static_logo.py --font <path to SourceSans3[wght].ttf>

The font is Source Sans 3 (SIL Open Font License), from Google Fonts' own repository:
https://github.com/google/fonts/tree/main/ofl/sourcesans3 (SourceSans3[wght].ttf). It isn't kept here.
Needs Edge or Chrome and an internet connection: the generator measures the lettering as the browser draws
it with the web font, to place the S dip.

How: the browser draws the sticker and the icon exactly as preview.html does and reports where it put each
letter. Each letter is then replaced by its outline from the font at weight 700, in that spot. A check draws
the live version and the static one at the same size and stops unless they differ only along edges
(antialiasing) and the lettering lines up best unshifted.

Writes, in this folder:
  pebbl_sticker_print.svg, .pdf    the print file: the 1.732 x 2 in cut plus 1/16 in bleed (1.857 x 2.125 in)
  pebbl_sticker_print_600dpi.png   the same at 600 dpi (1114 x 1275 px)
  pebbl_sticker_proof.svg          with the cut line (pink), the 1/8 in safe zone (blue) and the bleed edge (gray)
  pebbl_sticker.svg                the sticker as cut, for screens
  pebbl_icon.svg, pebbl_icon_256.png, _128, _64, _32   the icon (square PNGs, transparent around the hexagon)
docs/build_manual_pdf.py makes the manual's logo, docs/img/pebbl_icon.png and pebbl.ico from pebbl_icon.svg.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "docs"))
from build_manual_pdf import browser  # noqa: E402

CORE_JS = os.path.join(HERE, "pebbl_core.js")
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
INK = "#22282A"
FONT_CSS = "https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@700&display=swap"
# The option sets in preview.html, unchanged. Units: 1000 = 1 inch.
STICKER = ("{W:1857,H:2125,border:80,bleed:62.5,seed:51,tries:8000,minR:38,maxR:140,line:8,tw:60,halo:130,gap:40,"
           "fs:450,textTop:250,dipBelowTop:45,tipDrop:170}")
ICON = ("{W:1732,H:2000,border:95,bleed:0,seed:61,tries:3500,minR:80,maxR:190,line:12,tw:100,halo:190,gap:40,fs:500,"
        "textTop:250,dipBelowTop:40,tipDrop:210}")
# Both drawn at fixed sizes: the sticker at 600 dpi, the icon 512 px wide.
LAYOUT = ("<style>html,body{margin:0;background:#fff}.guides{display:none}"
          "#s{position:absolute;left:0;top:0;width:1114px}#i{position:absolute;left:1150px;top:0;width:512px}"
          "#s img,#i img{display:block;width:100%}</style>")
CAPTURE = """<!doctype html><html><head><meta charset="utf-8"><link href="FONT_CSS" rel="stylesheet">LAYOUT</head>
<body><div id="s"></div><div id="i"></div><pre id="out"></pre><script>CORE</script><script>
function grab(host){
  var svg = host.querySelector("svg"), tx = svg.querySelector("text"), xs = [];
  for (var k = 0; k < tx.textContent.length; k++) xs.push(tx.getStartPositionOfChar(k).x);
  return {svg: svg.outerHTML, text: tx.textContent, xs: xs, y: parseFloat(tx.getAttribute("y")),
          fontSize: parseFloat(tx.style.fontSize), fontReady: document.fonts.check("700 100px 'Source Sans 3'")};
}
document.fonts.load("700 450px 'Source Sans 3'").then(function(){
  PEBBL(document.getElementById("s"), STICKER); PEBBL(document.getElementById("i"), ICON);
  document.getElementById("out").textContent = JSON.stringify({sticker: grab(document.getElementById("s")),
                                                               icon: grab(document.getElementById("i"))});
});
</script></body></html>"""
STATIC = ("<!doctype html><html><head><meta charset='utf-8'>" + LAYOUT + "</head><body><div id='s'>"
          "<img src='pebbl_sticker.svg'></div><div id='i'><img src='pebbl_icon.svg'></div></body></html>")
ONE = ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:transparent}"
       "img{display:block;width:%dpx}</style></head><body><img src='%s'></body></html>")
PDF_PAGE = ("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:1.857in 2.125in;margin:0}"
            "html,body{margin:0;overflow:hidden}svg{display:block;width:1.857in;height:2.125in}</style></head>"
            "<body>%s</body></html>")


def q(tag):
    return "{%s}%s" % (NS, tag)


def run_browser(page, args, folder, screen=True):
    """Opens `page` (HTML text) in a headless browser with `args`; returns its standard output."""
    fd, path = tempfile.mkstemp(suffix=".html", dir=folder)
    os.close(fd)
    profile = tempfile.mkdtemp(prefix="pebbl_logo_browser_")
    # Printing uses build_manual_pdf.py's flags only: with the screen flags the browser wrote the PDF but didn't exit.
    screen_flags = ["--hide-scrollbars", "--force-device-scale-factor=1"] if screen else []
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        return subprocess.run([browser(), "--headless", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                               "--virtual-time-budget=15000", "--run-all-compositor-stages-before-draw",
                               *screen_flags, *args, "file:///" + path.replace("\\", "/")],
                              check=True, capture_output=True, encoding="utf-8", timeout=180).stdout
    finally:
        os.remove(path)
        shutil.rmtree(profile, ignore_errors=True)


def screenshot(page, png, size, folder, transparent=False):
    run_browser(page, [f"--window-size={size[0]},{size[1]}", f"--screenshot={png}"]
                + (["--default-background-color=00000000"] if transparent else []), folder)


def capture(folder):
    with open(CORE_JS, encoding="utf-8") as f:
        core = f.read()
    page = (CAPTURE.replace("FONT_CSS", FONT_CSS).replace("LAYOUT", LAYOUT).replace("CORE", core)
            .replace("STICKER", STICKER).replace("ICON", ICON))
    found = re.search(r'<pre id="out">(.*?)</pre>', run_browser(page, ["--dump-dom"], folder), re.S)
    if not found or not found.group(1).strip():
        sys.exit("The browser didn't finish drawing the logo (is there an internet connection for the web font?).")
    caps = json.loads(html.unescape(found.group(1)))
    if not all(c["fontReady"] for c in caps.values()):
        sys.exit("The browser drew the logo without Source Sans 3 (the web font didn't load).")
    return caps


def lettering(font, cap):
    """One path for "pebbl": each glyph's outline at the capture's size, its origin where the browser put it."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    scale = cap["fontSize"] / font["head"].unitsPerEm
    glyphs, cmap, parts = font.getGlyphSet(), font.getBestCmap(), []
    for ch, x in zip(cap["text"], cap["xs"]):
        pen = SVGPathPen(glyphs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
        glyphs[cmap[ord(ch)]].draw(TransformPen(pen, (scale, 0, 0, -scale, x, cap["y"])))
        parts.append(pen.getCommands())
    return " ".join(parts)


def static_svg(cap, font, kind, bleed, guides):
    """The captured drawing with the lettering outlined; `bleed`/`guides` keep the bleed and the dashed guides."""
    markup = cap["svg"]
    if "xmlns=" not in markup.split(">", 1)[0]:  # a page's outerHTML leaves out the SVG namespace
        markup = markup.replace("<svg ", '<svg xmlns="%s" ' % NS, 1)
    root = ET.fromstring(markup)
    clip = root.find(".//" + q("clipPath"))
    old, new = clip.get("id"), "pebbl-%s-clip" % kind
    clip.set("id", new)
    for el in root.iter():
        if el.get("clip-path") == "url(#%s)" % old:
            el.set("clip-path", "url(#%s)" % new)
    for parent in list(root.iter()):
        for i, child in enumerate(list(parent)):
            if child.tag == q("text"):
                parent.remove(child)
                parent.insert(i, ET.Element(q("path"), {"d": lettering(font, cap), "fill": INK, "aria-label": "pebbl"}))
            elif child.get("class") == "guides" and child.tag == q("polygon"):  # the ink out to the bleed line
                if bleed:
                    del child.attrib["class"]
                else:
                    parent.remove(child)
            elif child.get("class") == "guides" and not guides:
                parent.remove(child)
    w, h = (float(v) for v in root.get("viewBox").split()[2:])
    root.set("width", "%gin" % (w / 1000) if kind == "sticker" else "%g" % (w / 10))
    root.set("height", "%gin" % (h / 1000) if kind == "sticker" else "%g" % (h / 10))
    title = ET.Element(q("title"))
    title.text = "PEBBL"
    root.insert(0, title)
    svg = ET.tostring(root, encoding="unicode")
    assert "<text" not in svg
    return svg


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote", os.path.basename(path))


def check(folder, core_page_dir):
    """Stops unless the live drawing and the static files differ only along edges, with the lettering unshifted."""
    with open(CORE_JS, encoding="utf-8") as f:
        core = f.read()
    live_page = ("<!doctype html><html><head><meta charset='utf-8'><link href='%s' rel='stylesheet'>%s</head><body>"
                 "<div id='s'></div><div id='i'></div><script>%s</script><script>document.fonts.load(\"700 450px "
                 "'Source Sans 3'\").then(function(){PEBBL(document.getElementById('s'),%s);"
                 "PEBBL(document.getElementById('i'),%s);});</script></body></html>") % (FONT_CSS, LAYOUT, core,
                                                                                          STICKER, ICON)
    tmp = tempfile.mkdtemp(prefix="pebbl_logo_check_")
    try:
        live, static = os.path.join(tmp, "live.png"), os.path.join(tmp, "static.png")
        screenshot(live_page, live, (1700, 1300), core_page_dir)
        screenshot(STATIC, static, (1700, 1300), folder)
        a = np.asarray(Image.open(live).convert("RGB")).astype(int)
        b = np.asarray(Image.open(static).convert("RGB")).astype(int)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    diff = np.abs(a - b).max(axis=2)
    gray = a.mean(axis=2)
    edge = np.zeros(gray.shape, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            edge |= np.abs(gray - np.roll(np.roll(gray, dy, 0), dx, 1)) > 32
    off_edge = int(((diff > 32) & ~edge).sum())
    k = 1114 / 1857  # the sticker's lettering, in pixels
    box = (slice(int(880 * k), int(1260 * k)), slice(int(350 * k), int(1380 * k)))
    shifted = {(sy, sx): int((np.abs(a - np.roll(np.roll(b, sy, 0), sx, 1)).max(axis=2)[box] > 32).sum())
               for sy in (-1, 0, 1) for sx in (-1, 0, 1)}
    print(f"check: {int((diff > 32).sum())} px differ by more than 32 levels (largest {int(diff.max())}), "
          f"{off_edge} of them off an edge; lettering mismatch unshifted {shifted[0, 0]}, "
          f"best 1-px shift {min(v for s, v in shifted.items() if s != (0, 0))}")
    if off_edge or diff.max() > 128 or min(shifted, key=shifted.get) != (0, 0):
        sys.exit("The static files don't match the live drawing; nothing should be committed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--font", required=True, help="SourceSans3[wght].ttf from Google Fonts' repository")
    parser.add_argument("--out", default=HERE, help="where to write the files (default: this folder)")
    args = parser.parse_args()
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    variable = TTFont(args.font)
    if variable["name"].getDebugName(16) != "Source Sans 3" or "fvar" not in variable:  # 16: the family name
        sys.exit(f"{args.font} isn't Source Sans 3's variable font (SourceSans3[wght].ttf).")
    font = instancer.instantiateVariableFont(variable, {"wght": 700})
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    caps = capture(out)
    svgs = {"pebbl_sticker_print.svg": static_svg(caps["sticker"], font, "sticker", bleed=True, guides=False),
            "pebbl_sticker_proof.svg": static_svg(caps["sticker"], font, "sticker", bleed=True, guides=True),
            "pebbl_sticker.svg": static_svg(caps["sticker"], font, "sticker", bleed=False, guides=False),
            "pebbl_icon.svg": static_svg(caps["icon"], font, "icon", bleed=False, guides=False)}
    for name, svg in svgs.items():
        write(os.path.join(out, name), '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n")
    check(out, out)

    pdf = os.path.join(out, "pebbl_sticker_print.pdf")
    run_browser(PDF_PAGE % svgs["pebbl_sticker_print.svg"], ["--no-pdf-header-footer", f"--print-to-pdf={pdf}"], out,
                screen=False)
    with open(pdf, "rb") as f:
        pages = len(re.findall(rb"/Type\s*/Page[^s]", f.read()))
    if pages != 1:
        sys.exit(f"The print PDF has {pages} pages, not 1.")
    print("wrote", os.path.basename(pdf))
    png = os.path.join(out, "pebbl_sticker_print_600dpi.png")
    screenshot(ONE % (1114, "pebbl_sticker_print.svg"), png, (1114, 1275), out, transparent=True)
    print("wrote", os.path.basename(png))
    big = os.path.join(out, "pebbl_icon_render.png")
    screenshot(ONE % (887, "pebbl_icon.svg"), big, (887, 1024), out, transparent=True)
    icon = Image.open(big).convert("RGBA")
    os.remove(big)
    icon = icon.crop(icon.getchannel("A").getbbox())
    side = max(icon.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(icon, ((side - icon.width) // 2, (side - icon.height) // 2))
    for size in (256, 128, 64, 32):
        square.resize((size, size), Image.LANCZOS).save(os.path.join(out, f"pebbl_icon_{size}.png"))
        print(f"wrote pebbl_icon_{size}.png")


if __name__ == "__main__":
    main()
