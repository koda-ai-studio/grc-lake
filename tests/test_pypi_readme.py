"""The PyPI page renders README.md without the repository around it."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from pypi_readme import absolutize, main, relative_links
from verify_wheel import published_readme_problems

BLOB = "https://github.com/koda-ai-studio/grc-lake/blob/v1.2.3"
RAW = "https://raw.githubusercontent.com/koda-ai-studio/grc-lake/v1.2.3"
README = Path(__file__).resolve().parents[1] / "README.md"


def test_markdown_links_point_at_the_tagged_file() -> None:
    text = "See [Docs](docs/README.md) and [OCSF](docs/BRING_YOUR_OWN_LAKE.md#ocsf-events)."
    assert absolutize(text, "v1.2.3") == (
        f"See [Docs]({BLOB}/docs/README.md) and [OCSF]({BLOB}/docs/BRING_YOUR_OWN_LAKE.md#ocsf-events)."
    )


def test_images_point_at_raw_tagged_bytes() -> None:
    text = (
        '<picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/a-dark.png">'
        '<img src="docs/images/a.png" alt="A"></picture> ![B](docs/images/b.svg)'
    )
    assert absolutize(text, "v1.2.3") == (
        f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}/docs/images/a-dark.png">'
        f'<img src="{RAW}/docs/images/a.png" alt="A"></picture> ![B]({RAW}/docs/images/b.svg)'
    )


def test_html_links_point_at_the_tagged_file() -> None:
    assert absolutize('<a href="LICENSE">Apache-2.0</a>', "v1.2.3") == f'<a href="{BLOB}/LICENSE">Apache-2.0</a>'


def test_absolute_urls_anchors_and_mail_are_unchanged() -> None:
    text = '[a](https://example.com/x.md) [b](#frameworks) [c](mailto:x@example.com) <a href="#top">t</a>'
    assert absolutize(text, "v1.2.3") == text
    assert relative_links(text) == []


def test_the_real_readme_has_no_relative_links_after_rewriting() -> None:
    text = README.read_text()
    assert relative_links(text), "README.md is expected to use repository-relative links"
    assert relative_links(absolutize(text, "v1.2.3")) == []


def test_main_rewrites_in_place(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("[Docs](docs/README.md)\n")
    assert main([str(readme), "--ref", "v1.2.3"]) == 0
    assert readme.read_text() == f"[Docs]({BLOB}/docs/README.md)\n"


def _wheel_with_description(tmp_path: Path, description: str) -> Path:
    wheel = tmp_path / "grc_lake-1.2.3-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.4\nName: grc-lake\nVersion: 1.2.3\n\n{description}"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("grc_lake-1.2.3.dist-info/METADATA", metadata)
    return wheel


def test_published_wheel_gate_rejects_relative_readme_links(tmp_path: Path) -> None:
    problems = published_readme_problems(_wheel_with_description(tmp_path, '<img src="docs/images/a.png">'))
    assert problems and "docs/images/a.png" in problems[0]


def test_published_wheel_gate_accepts_absolute_readme_links(tmp_path: Path) -> None:
    assert published_readme_problems(_wheel_with_description(tmp_path, f'<img src="{RAW}/docs/images/a.png">')) == []
