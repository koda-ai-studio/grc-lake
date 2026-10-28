"""README hero assets stay sharp, accessible, and wired into the product story."""

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from tools.render_readme_header import (
    CCF_COLUMN,
    estimate_text_width,
    render_logo,
    render_open_graph,
    render_readme_glance,
    render_social_preview,
)

from security_lakehouse.safeguards import coverage_by_framework

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ASSETS = (
    ROOT / "docs" / "images" / "grc-lake-capability-header.svg",
    ROOT / "docs" / "images" / "grc-lake-logo.svg",
    ROOT / "docs" / "images" / "grc-lake-readme-banner.svg",
    ROOT / "app" / "web" / "public" / "og" / "grc-lake-share.svg",
)


def test_readme_header_leads_with_the_product_and_live_build_status() -> None:
    readme = README.read_text(encoding="utf-8")
    header = readme.split("## Quick start", maxsplit=1)[0]
    assert 'src="docs/images/grc-lake-capability-header.svg"' in header
    assert "traceable control assessments and reviewable audit workpapers" in header
    assert "Open, self-hosted GRC for cloud and AI." not in header, "one tagline only"
    assert "Quick start" in header
    assert "ci.yml?branch=main&amp;label=CI" in header
    opening_tags = readme.count("<details>") + readme.count("<details open>")
    assert opening_tags == readme.count("</details>") >= 1


def test_readme_hero_names_only_shipped_capabilities() -> None:
    root = ElementTree.parse(ASSETS[0]).getroot()
    copy = " ".join(text.strip() for text in root.itertext() if text.strip())
    coverage = coverage_by_framework()

    assert "Collect. Evaluate. Resolve. Export." in copy
    assert "GRC Lake" in copy
    assert "Read-only evidence" in copy
    assert "deterministic controls" in copy
    assert "owned findings" in copy
    assert "assessment exports" in copy
    assert f"{coverage['safeguards']:,} safeguards · {coverage['controls']:,} catalogued requirements" in copy
    assert f"{len(coverage['frameworks'])} framework packs" in copy
    assert "Console · API · CLI · MCP · CI" in copy
    desc = "".join(root.find(f"{SVG}desc").itertext())
    assert "immutable" not in desc
    assert "hash-chained, verifiable audit records" in desc
    source_ids = {
        "AWS": "aws-posture",
        "Azure": "azure-posture",
        "GCP": "gcp-posture",
        "GitHub": "github-security",
        "GitLab": "gitlab-security",
        "Okta": "okta-identity",
        "Snowflake": "snowflake-evidence-lake",
        "ClickHouse": "clickhouse-telemetry-lake",
    }
    connector_payload = json.loads((ROOT / "connectors" / "catalog.json").read_text(encoding="utf-8"))
    connectors = {entry["connector_id"]: entry for entry in connector_payload["connectors"]}
    for source, connector_id in source_ids.items():
        assert source in copy
        assert connectors[connector_id]["is_implemented"] is True
        assert connectors[connector_id]["collection_mode"] in {"direct_api_read", "existing_lake_read"}
    for framework in (
        "SOC 2",
        "ISO 27001",
        "FedRAMP",
        "CMMC",
        "NIST CSF",
        "CIS AWS",
        "HIPAA",
        "PCI DSS",
        "GDPR",
        "EU AI Act",
        "ISO 27017",
        "ISO 42001",
        "NIST AI RMF",
    ):
        assert framework in copy


SVG = "{http://www.w3.org/2000/svg}"


def _translate(element: ElementTree.Element) -> tuple[float, float]:
    transform = element.attrib.get("transform", "")
    if not transform.startswith("translate("):
        return 0.0, 0.0
    x, _, y = transform.removeprefix("translate(").removesuffix(")").partition(" ")
    return float(x), float(y or 0)


def _placed_text(element: ElementTree.Element, origin: tuple[float, float] = (0.0, 0.0)):
    """Yield (absolute left, absolute right, text) for every <text> in the hero."""
    dx, dy = _translate(element)
    origin = (origin[0] + dx, origin[1] + dy)
    for child in element:
        if child.tag == f"{SVG}text":
            copy = "".join(child.itertext())
            size = float(child.attrib.get("font-size", "16"))
            spacing = float(child.attrib.get("letter-spacing", "0"))
            width = estimate_text_width(copy, size, letter_spacing=spacing)
            x = origin[0] + float(child.attrib.get("x", "0"))
            anchor = child.attrib.get("text-anchor", "start")
            left = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
            yield left, left + width, copy
        elif child.tag == f"{SVG}g":
            yield from _placed_text(child, origin)


def test_readme_hero_text_fits_the_view_box_and_the_ccf_column() -> None:
    root = ElementTree.parse(ASSETS[0]).getroot()
    width = float(root.attrib["viewBox"].split()[2])
    column_left, column_right = CCF_COLUMN
    placed = list(_placed_text(root))
    for left, right, copy in placed:
        assert left >= 0 and right <= width, f"{copy!r} overflows the header"
    column = [(left, right, copy) for left, right, copy in placed if left >= column_left - 1 and "Console" not in copy]
    assert any("framework packs" in copy for _, _, copy in column)
    for _, right, copy in column:
        assert right <= column_right, f"{copy!r} overflows the control framework column"


@pytest.mark.parametrize(
    ("copy", "size", "rendered"),
    [
        # Widths Chromium rendered for these hero lines with the system-ui fallback.
        ("SOC 2 · ISO 27001 · NIST 800-53 · NIST RMF · FedRAMP · CMMC · NIST CSF", 12, 446),
        ("CIS Controls · CIS AWS · HIPAA · PCI DSS · GDPR · EU AI Act · ISO 27017", 12, 422),
        ("78 safeguards · 2,031 catalogued requirements", 13, 302),
        ("Read-only evidence → deterministic controls → owned findings → assessment exports.", 17, 678),
    ],
)
def test_estimated_text_width_never_undershoots_a_real_render(copy: str, size: float, rendered: int) -> None:
    assert estimate_text_width(copy, size) >= rendered
    assert estimate_text_width("", size) == 0


def test_readme_hero_counts_the_read_only_sources_it_leaves_out() -> None:
    root = ElementTree.parse(ASSETS[0]).getroot()
    copy = " ".join(text.strip() for text in root.itertext() if text.strip())
    connectors = json.loads((ROOT / "connectors" / "catalog.json").read_text(encoding="utf-8"))["connectors"]
    generally_available = [
        entry
        for entry in connectors
        if entry.get("is_implemented") is True
        and entry.get("release_stage") != "preview"
        and entry["collection_mode"] in {"direct_api_read", "existing_lake_read"}
    ]
    preview = [
        entry
        for entry in connectors
        if entry.get("is_implemented") is True
        and entry.get("release_stage") == "preview"
        and entry["collection_mode"] in {"direct_api_read", "existing_lake_read"}
    ]
    assert "STANDARD READ-ONLY SOURCES" in copy
    assert "GENERALLY AVAILABLE" not in copy, "the ga label does not prove a live run"
    total = len(generally_available) + len(preview)
    assert f"{total} read-only source adapters ({len(preview)} preview)" in copy
    tiled = {
        "aws-posture",
        "azure-posture",
        "gcp-posture",
        "github-security",
        "gitlab-security",
        "okta-identity",
        "snowflake-evidence-lake",
        "clickhouse-telemetry-lake",
    }
    assert tiled.isdisjoint(entry["connector_id"] for entry in preview)
    # GA + preview is the executable count the README states once.
    executable = [entry for entry in connectors if entry.get("is_implemented") is True]
    assert len(generally_available) + len(preview) == len(executable)
    readme = README.read_text(encoding="utf-8")
    assert "connectors/catalog.json" in readme


def test_readme_hero_does_not_repeat_itself() -> None:
    root = ElementTree.parse(ASSETS[0]).getroot()
    texts = ["".join(node.itertext()) for node in root.iter(f"{SVG}text")]
    # The subtitle already says evidence -> controls -> findings -> exports.
    assert not any("evidence → controls → findings → proof" in text for text in texts)
    # One text run for the headline, so the browser spaces the words evenly.
    headline = [text for text in texts if text.startswith("Collect.")]
    assert headline == ["Collect. Evaluate. Resolve. Export."]


def test_readme_heroes_identify_preview_lake_adapters_separately() -> None:
    from tools.render_readme_header import render_mobile_preview

    catalog = json.loads((ROOT / "connectors/catalog.json").read_text())["connectors"]
    connectors = {entry["connector_id"]: entry for entry in catalog}
    for render in (render_social_preview, render_mobile_preview):
        root = ElementTree.fromstring(render())
        preview = root.find(f".//{SVG}g[@id='preview-lakes']")
        assert preview is not None, "Preview lakes need an explicitly labelled group"
        copy = " ".join(preview.itertext())
        assert "Preview" in copy
        for name, connector_id in (
            ("Databricks", "databricks-evidence-lake"),
            ("BigQuery", "bigquery-evidence-lake"),
            ("Iceberg", "iceberg-parquet-lake"),
        ):
            assert name in copy
            assert connectors[connector_id]["release_stage"] == "preview"
            assert connectors[connector_id]["is_implemented"] is True


def test_readme_visuals_are_accessible_scalable_svg_assets() -> None:
    for path in ASSETS:
        assert path.is_file(), f"README visual is missing: {path.relative_to(ROOT)}"
        root = ElementTree.parse(path).getroot()
        assert root.attrib.get("viewBox"), f"{path.name} needs a viewBox for crisp scaling"
        assert root.attrib.get("role") == "img"
        labelled_by = root.attrib.get("aria-labelledby", "").split()
        assert labelled_by == ["title", "desc"]

        children = {child.tag.rsplit("}", 1)[-1]: child for child in root}
        assert children["title"].text
        assert children["desc"].text


def test_readme_hero_matches_the_deterministic_renderer() -> None:
    assert ASSETS[0].read_text(encoding="utf-8") == render_social_preview()


def test_readme_logo_matches_the_deterministic_renderer() -> None:
    assert ASSETS[1].read_text(encoding="utf-8") == render_logo()


def test_open_graph_image_matches_the_deterministic_renderer() -> None:
    assert ASSETS[3].read_text(encoding="utf-8") == render_open_graph()


def test_operating_loop_uses_concrete_actions() -> None:
    readme = README.read_text(encoding="utf-8")
    section = readme.split("## Product tour", maxsplit=1)[1].split("## Self-host", maxsplit=1)[0]
    for action in ("Collect", "Evaluate", "Resolve", "Export"):
        assert action in section


def test_product_preview_shows_distinct_views_without_repeating_the_overview() -> None:
    readme = README.read_text(encoding="utf-8")
    tour = readme.split("## Product tour", maxsplit=1)[1].split("## Architecture", maxsplit=1)[0]
    assert "bundled synthetic company" in tour
    assert "<details>" not in tour
    views = ("dashboard", "frameworks", "controls", "graph", "ai-governance")
    assert tour.count("<picture>") == len(views)
    positions = []
    for view in views:
        for theme in ("", "-dark"):
            image = f"docs/images/grc-lake-demo-{view}{theme}.png"
            assert tour.count(image) == 1
            assert (ROOT / image).is_file()
        positions.append(tour.index(f"grc-lake-demo-{view}.png"))
    assert positions == sorted(positions)
    assert "grc-lake-demo-control-families" not in tour
    assert "### Navigate control families and the CCF" in tour
    assert "Proposed mappings are not attestable." in tour
    assert "<!-- BEGIN README CCF SUMMARY -->" not in readme
    assert "docs/FRAMEWORK_COVERAGE.md" in readme
    assert "docs/COMMON_CONTROL_FRAMEWORK.md" in readme


def test_readme_glance_matches_the_generator_and_the_catalogs() -> None:
    readme = README.read_text(encoding="utf-8")
    block = readme.split("<!-- BEGIN README AT A GLANCE -->", maxsplit=1)[1].split(
        "<!-- END README AT A GLANCE -->", maxsplit=1
    )[0]
    assert block == f"\n\n{render_readme_glance()}\n\n"

    coverage = coverage_by_framework()
    connectors = json.loads((ROOT / "connectors" / "catalog.json").read_text(encoding="utf-8"))["connectors"]
    runnable = [
        entry
        for entry in connectors
        if entry.get("is_implemented") is True and entry["collection_mode"] in {"direct_api_read", "existing_lake_read"}
    ]
    preview = [entry for entry in runnable if entry.get("release_stage") == "preview"]
    assert f"{len(coverage['frameworks'])} framework packs" in block
    assert f"{coverage['controls']:,} catalogued requirements" in block
    assert f"{coverage['safeguards']:,} safeguards, including source-native assessment contracts" in block
    assert f"{coverage['covered']:,} requirements have safeguard mappings" in block
    assert (
        f"{coverage['reviewed']:,} have reviewed mappings and the other {coverage['proposed']:,} are proposed" in block
    )
    assert coverage["reviewed"] + coverage["proposed"] == coverage["covered"]
    assert (
        f"{len(runnable)} executable adapters ({len(runnable) - len(preview)} implemented, {len(preview)} preview)"
        in block
    )
    assert (
        f"Of the reviewed, {coverage['source_native_reviewed']:,} are source-native self-maps" in block
        and f"{coverage['crosswalk_reviewed']:,} rest on reviewed crosswalk mappings" in block
        and f"{coverage['legacy_only_reviewed']:,} rest only on legacy reviews with no recorded reviewer" in block
    )
    assert coverage["source_native_reviewed"] + coverage["crosswalk_reviewed"] == coverage["reviewed"]
    assert "The blended total is not a per-framework readiness figure." in block


def test_readme_glance_leads_with_per_framework_reviewed_coverage() -> None:
    from tools.render_readme_header import HEADLINE_FRAMEWORKS

    readme = README.read_text(encoding="utf-8")
    block = readme.split("<!-- BEGIN README AT A GLANCE -->", maxsplit=1)[1].split(
        "<!-- END README AT A GLANCE -->", maxsplit=1
    )[0]
    bullets = [line for line in block.splitlines() if line.startswith("- ")]
    assert 4 <= len(bullets) <= 6
    lead = bullets[0]
    assert lead.startswith("- **Reviewed requirements by framework:**")
    frameworks = coverage_by_framework()["frameworks"]
    positions = []
    for framework_id, label in HEADLINE_FRAMEWORKS:
        row = frameworks[framework_id]
        phrase = f"{label} {row['reviewed']:,}/{row['controls']:,}"
        assert phrase in lead, phrase
        positions.append(lead.index(phrase))
        notes = []
        if row["source_native_reviewed"]:
            notes.append(f"{row['source_native_reviewed']:,} source-native self-maps")
        if row["legacy_only_reviewed"]:
            notes.append(f"{row['legacy_only_reviewed']:,} with no recorded reviewer")
        if notes:
            assert f"{phrase} ({'; '.join(notes)})" in lead
    assert positions == sorted(positions)
    assert "PCI DSS" in lead and "(top-level)" in lead
    assert frameworks["nist-800-53-rev5"]["source_native_reviewed"] > 0
    # The blended aggregate is qualified, never the lead bullet.
    assert f"{coverage_by_framework()['reviewed']:,} have reviewed mappings" not in lead


def test_readme_counts_baseline_restatements_once() -> None:
    from tools.render_readme_header import restated_requirement_count

    catalog = json.loads((ROOT / "controls" / "catalog.json").read_text(encoding="utf-8"))["controls"]
    ids = {row["control_id"] for row in catalog}
    fedramp = [row["control_id"] for row in catalog if row["framework_id"] == "fedramp-moderate"]
    assert fedramp and all(f"NIST-800-53-{cid.removeprefix('FEDRAMP-')}" in ids for cid in fedramp)
    restated = restated_requirement_count()
    assert restated == len(fedramp)
    distinct = f"{len(catalog) - restated:,} distinct"
    assert distinct in render_readme_glance()


def test_mobile_readme_hero_is_legible_at_github_content_width():
    readme = README.read_text()
    assert 'media="(max-width: 640px)"' in readme
    mobile = ROOT / "docs/images/grc-lake-capability-header-mobile.svg"
    root = ElementTree.parse(mobile).getroot()
    width = float(root.attrib["viewBox"].split()[2])
    for node in root.iter(f"{SVG}text"):
        assert float(node.attrib["font-size"]) * 324 / width >= 12
    for left, right, copy in _placed_text(root):
        assert 0 <= left <= right <= width, copy
    from tools.render_readme_header import render_mobile_preview

    assert mobile.read_text() == render_mobile_preview()
