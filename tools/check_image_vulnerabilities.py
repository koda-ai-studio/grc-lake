#!/usr/bin/env python3
"""Gate an unfiltered Trivy image report, including unfixed high findings."""

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        report = json.loads(Path(sys.argv[1]).read_text())
        metadata = report["Metadata"]
        results = report["Results"]
        if (
            report["ArtifactType"] != "container_image"
            or not metadata["ImageID"]
            or not metadata["OS"]["Family"]
            or not any(result.get("Class") == "os-pkgs" for result in results)
        ):
            raise ValueError("missing image identity or OS package scan")
        blocked = []
        for result in results:
            for finding in result.get("Vulnerabilities") or []:
                severity = finding["Severity"]
                if severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                    raise ValueError(f"unknown severity: {severity!r}")
                if not finding["VulnerabilityID"] or not finding["PkgName"]:
                    raise ValueError("finding lacks an advisory or package identity")
                if severity in {"HIGH", "CRITICAL"} or (severity == "MEDIUM" and finding.get("FixedVersion")):
                    blocked.append(finding)
    except (IndexError, KeyError, TypeError, ValueError, OSError) as error:
        print(f"Incomplete or invalid image scan: {error}", file=sys.stderr)
        return 2
    for finding in blocked:
        print(
            f"{finding['Severity']} {finding['VulnerabilityID']} {finding['PkgName']}: "
            f"{finding.get('InstalledVersion', '?')} -> {finding.get('FixedVersion') or 'no listed fix'}"
        )
    if blocked:
        print(f"Image policy failed: {len(blocked)} blocking findings")
        return 1
    print("Image policy passed: zero HIGH/CRITICAL and zero fixable MEDIUM findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
