"""Refresh CCF documentation figures from the same version-aware coverage API."""

import re
from pathlib import Path

from security_lakehouse.safeguards import (
    LEGACY_REVIEW_RECORD,
    broadest_safeguards,
    contributes_to_coverage,
    coverage_by_family,
    coverage_by_framework,
    effective_review_state,
    load_safeguards,
)


def broadest_table(coverage):
    """Prettier-aligned so the formatter and this generator agree."""
    header = ["Safeguard", "Title", "Requirements", "Frameworks", "Reviewed", "Legacy, no reviewer", "Proposed"]
    body = [
        [
            f"`{row['safeguard_id']}`",
            str(row["title"]),
            *(str(row[key]) for key in ("requirements", "frameworks", "reviewed", "legacy_unattributed", "proposed")),
        ]
        for row in broadest_safeguards()
    ]
    widths = [max(len(cells[i]) for cells in [header, *body]) for i in range(len(header))]

    def line(cells):
        padded = [
            cell.ljust(w) if i < 2 else cell.rjust(w) for i, (cell, w) in enumerate(zip(cells, widths, strict=False))
        ]
        return "| " + " | ".join(padded) + " |"

    rule = "| " + " | ".join("-" * w if i < 2 else "-" * (w - 1) + ":" for i, w in enumerate(widths)) + " |"
    lines = ["", line(header), rule, *(line(cells) for cells in body)]
    legacy = (
        f"\n{coverage['legacy_only_reviewed']} of the {coverage['reviewed']} reviewed requirements rest only on "
        f"legacy reviews with no recorded reviewer ({coverage['legacy_unattributed_mappings']} mappings, listed "
        f"with their originating commits in [the legacy record](../{LEGACY_REVIEW_RECORD})); the other "
        f"{coverage['receipt_reviewed']} have a decision receipt or an org decision.\n"
    )
    return "\n".join(lines) + "\n" + legacy


def main():
    coverage = coverage_by_framework()
    path = Path(__file__).resolve().parents[1] / "docs/COMMON_CONTROL_FRAMEWORK.md"
    text = path.read_text()
    headline = (
        f"{coverage['safeguards']} safeguards map {coverage['covered']} of {coverage['controls']} requirements "
        f"({coverage['coverage_pct']}%) — {coverage['maintainer_reviewed']} maintainer-reviewed, "
        f"{coverage['org_reviewed']} org-reviewed ({coverage['reviewed_pct']}% attestable), "
        f"{coverage['proposed']} proposed; {coverage['rejected_mappings']} mapping(s) rejected by the org"
    )
    text = re.sub(r"^\d+ safeguards map .*$", lambda _: headline, text, flags=re.M)
    for row in coverage_by_family():
        pattern = r"(^\|[^\n]*\| `" + re.escape(row["family_id"]) + r"`\s*\|)\s*\d+(\s*\|)"
        text = re.sub(
            pattern, lambda match, row=row: f"{match[1]} {row['safeguard_count']:10d}{match[2]}", text, flags=re.M
        )
    for name, row in coverage["frameworks"].items():
        line = f"| {name:19s} | {row['controls']:12d} | {row['covered']:6d} | {row['coverage_pct']:5.1f}% |"
        text = re.sub(r"^\| " + re.escape(name) + r"\s+\|.*$", lambda _, line=line: line, text, flags=re.M)
    text = re.sub(r"\b\d+ requirements, each carrying", f"{coverage['controls']} requirements, each carrying", text)
    text = re.sub(r"\b\d+ distinct evidence", f"{coverage['controls']} distinct evidence", text)
    text = re.sub(r"statements for \d+ controls", f"statements for {coverage['controls']} controls", text)
    text = re.sub(
        r"`asset_types` on all \d+ requirements", f"`asset_types` on all {coverage['controls']} requirements", text
    )
    text = re.sub(r"\d+ of \d+ titles still contain", "Some titles still contain", text)
    text = re.sub(
        r"(<!-- broadest-safeguards:start -->\n).*?(<!-- broadest-safeguards:end -->)",
        lambda match: match[1] + broadest_table(coverage) + match[2],
        text,
        flags=re.S,
    )
    path.write_text(text)
    states = [
        effective_review_state(member)
        for safeguard in load_safeguards()["safeguards"]
        for member in safeguard["satisfies"]
        if contributes_to_coverage(member)
    ]
    roadmap = path.parent.parent / "ROADMAP.md"
    roadmap.write_text(
        re.sub(
            r"^[\d,]+ of [\d,]+ safeguard-to-requirement mapping rows are proposed, .*?$",
            f"{states.count('proposed'):,} of {len(states):,} safeguard-to-requirement mapping rows are proposed, "
            f"so {coverage['proposed']:,} of the {coverage['covered']:,} mapped requirements have no reviewed mapping.",
            roadmap.read_text(),
            flags=re.M,
        )
    )


if __name__ == "__main__":
    main()
