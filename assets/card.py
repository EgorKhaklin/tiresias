"""Render the repository's social preview card (1280 x 640) from the dark lockup.

    python assets/card.py        (needs Google Chrome or Chromium on PATH or in /Applications)

The card is the README lockup, centred between two meander rules on the house dark ground. The
lockup's animation is stopped at its last frame. Writes social-preview.png next to this file;
upload it under the repository's Settings, Social preview.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCKUP = next(p for p in sorted(HERE.glob("*-dark.svg")) if not p.name.startswith(("rule", "glass-mark", "tiresias-mark")))
CHROME = [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser")] + [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]

PAGE = """<!doctype html><html><head><style>
*{{animation-duration:0s!important;animation-delay:0s!important;animation-iteration-count:1!important}}
html,body{{margin:0;width:1280px;height:640px;overflow:hidden;background:#0d1117}}
.card{{position:relative;width:1280px;height:640px;background:radial-gradient(ellipse 70% 60% at 50% 50%,#121a24 0%,#0d1117 70%)}}
.lock{{position:absolute;left:40px;top:138px;width:1200px}} .lock svg{{width:1200px;height:auto;display:block}}
.rule{{position:absolute;left:140px;width:1000px}} .rule svg{{width:1000px;height:auto;display:block}}
.top{{top:62px;transform:scaleY(-1)}} .bottom{{top:540px}}
</style></head><body><div class="card">
<div class="rule top">{rule}</div><div class="lock">{lockup}</div><div class="rule bottom">{rule}</div>
</div></body></html>"""


def main():
    chrome = next((c for c in CHROME if c and os.path.exists(c)), None)
    if chrome is None:
        raise SystemExit("card.py: Chrome or Chromium is needed to render the card")
    html = PAGE.format(rule=(HERE / "rule-dark.svg").read_text(), lockup=LOCKUP.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "card.html"
        page.write_text(html)
        out = HERE / "social-preview.png"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=1280,640", "--virtual-time-budget=3000", "--screenshot=%s" % out, page.as_uri()],
                       check=True, capture_output=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
