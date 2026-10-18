"""Documentation checks: links resolve, cited tests exist, README commands parse."""

import re
import shlex

import pytest

from afid.cli import build_parser
from tests.conftest import REPO

DOCS = [REPO / "README.md", REPO / "SECURITY.md", *sorted((REPO / "docs").glob("*.md"))]
TEST_SOURCES = "\n".join(p.read_text() for p in (REPO / "tests").rglob("test_*.py"))


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_relative_links_resolve(doc):
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^[a-z]+:|^#", target):
            continue
        assert (doc.parent / target.split("#")[0]).exists(), f"{doc.name}: broken link {target}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_cited_tests_exist(doc):
    for name in re.findall(r"`(test_[a-z0-9_]+)`", doc.read_text()):
        assert f"def {name}(" in TEST_SOURCES, f"{doc.name} cites missing test {name}"


def readme_commands():
    blocks = re.findall(r"```bash\n(.*?)```", (REPO / "README.md").read_text(), flags=re.S)
    for block in blocks:
        for line in block.replace("\\\n", " ").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("afid ") and "&&" not in line:
                yield line


@pytest.mark.parametrize("line", list(readme_commands()))
def test_readme_commands_parse(line):
    line = re.sub(r"\[[^\]]*\]", "", line)  # drop optional parts
    line = re.sub(r"<[^>]+>", "x", line)  # fill placeholders
    line = line.replace("json|markdown", "json")
    args = shlex.split(line)[1:]
    if args == ["--help"]:
        return
    ns = build_parser().parse_args(args)  # raises SystemExit on bad usage
    assert callable(ns.fn)
