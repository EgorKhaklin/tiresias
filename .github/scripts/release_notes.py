"""Print the CHANGELOG entry for a release tag, or its title with --title.

    python .github/scripts/release_notes.py v1.0.0            # the entry body
    python .github/scripts/release_notes.py v1.0.0 --title    # "<project> v1.0.0: <title>"

Exits 1 if the changelog has no entry for the tag, so a release cannot be cut
without one. Entries are headed `## vX.Y.Z - YYYY-MM-DD (title)`.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def entry(tag, text):
    head = re.compile(r"^## " + re.escape(tag) + r" - (\d{4}-\d{2}-\d{2})(?: \((.*)\))?\s*$", re.M)
    m = head.search(text)
    if not m:
        return None
    nxt = re.compile(r"^## ", re.M).search(text, m.end())
    body = text[m.end():nxt.start() if nxt else len(text)].strip("\n")
    return m.group(2) or "", body


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    tag = argv[1]
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        found = entry(tag, f.read())
    if found is None:
        print(f"CHANGELOG.md has no entry headed '## {tag} - <date>'", file=sys.stderr)
        return 1
    title, body = found
    if "--title" in argv:
        project = os.environ.get("PROJECT", os.path.basename(ROOT))
        print(f"{project} {tag}" + (f": {title}" if title else ""))
    else:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
