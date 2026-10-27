"""The docs hold together: every relative Markdown link under docs/ and in the root README resolves to a file, superseded
documents live in docs/history/, and its README lists each of them (roadmap I3)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
HISTORY = DOCS / "history"
LINK = re.compile(r"\[[^\]]*\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Run outputs stay on the lab machine (`runs/` is in .gitignore); reports link them as local evidence.
LOCAL_EVIDENCE = (ROOT / "runs").resolve()


def pages():
    return [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]


def links(text):
    """Relative link targets of a Markdown text, without their fragment; code blocks are skipped."""
    for match in LINK.finditer(FENCE.sub("", text)):
        target = match.group(1)
        if SCHEME.match(target) or target.startswith(("#", "/")):
            continue
        path = target.split("#", 1)[0]
        if path:
            yield path


def broken(page):
    found = []
    for path in links(page.read_text(encoding="utf-8")):
        resolved = (page.parent / path).resolve()
        if resolved.is_relative_to(LOCAL_EVIDENCE):
            continue
        if not resolved.exists():
            found.append(f"{page.relative_to(ROOT) if page.is_relative_to(ROOT) else page.name}: {path}")
    return found


def test_every_relative_markdown_link_resolves():
    found = [line for page in pages() for line in broken(page)]
    assert not found, "Links to files that do not exist:\n" + "\n".join(found)


def test_a_link_to_a_missing_file_is_caught(tmp_path):
    page = tmp_path / "page.md"
    (tmp_path / "there.md").write_text("# There\n", encoding="utf-8")
    page.write_text("[ok](there.md#part) [web](https://example.org) [anchor](#top)\n"
                    "```\n[in code](nowhere.md)\n```\n[moved](gone.md)\n", encoding="utf-8")
    assert list(links(page.read_text(encoding="utf-8"))) == ["there.md", "gone.md"]
    assert broken(page) == ["page.md: gone.md"]


def superseded(page):
    head = page.read_text(encoding="utf-8").splitlines()[:6]
    return any(line.startswith("> **Superseded") for line in head)


def test_superseded_documents_are_in_history():
    outside = [str(page.relative_to(ROOT)) for page in DOCS.rglob("*.md")
               if superseded(page) and HISTORY not in page.parents]
    assert not outside, "Superseded documents outside docs/history/: " + ", ".join(outside)


def test_history_lists_each_document_and_each_keeps_its_banner():
    index = (HISTORY / "README.md").read_text(encoding="utf-8")
    listed = set(links(index))
    for page in HISTORY.glob("*.md"):
        if page.name == "README.md":
            continue
        assert page.name in listed, f"docs/history/README.md does not list {page.name}"
        assert superseded(page), f"{page.name} has no Superseded banner"
