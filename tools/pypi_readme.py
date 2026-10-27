"""Pin README.md's repository-relative links to a release tag before packaging.

PyPI renders the package description without the repository around it, so
relative screenshots and document links break on the project page. The release
workflow rewrites the checkout's README.md just before `uv build`; the
repository copy keeps relative links and its published-install tag for GitHub.
The built description's Docker quick start follows the release being packaged.

    python tools/pypi_readme.py README.md --ref v0.3.12
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPOSITORY = "koda-ai-studio/grc-lake"
_SKIP = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/)", re.IGNORECASE)
_IMAGE_SUFFIXES = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp")
_HTML = re.compile(r'(?P<lead>\b(?P<attr>src|srcset|href)=")(?P<target>[^"]+)(?P<tail>")')
_MARKDOWN = re.compile(r"(?P<lead>(?P<bang>!?)\[[^\]]*\]\()(?P<target>[^)\s]+)(?P<tail>\))")


def _is_relative(target: str) -> bool:
    return not _SKIP.match(target)


def _is_image(attr: str, target: str) -> bool:
    return attr in {"src", "srcset", "!"} or target.split("#", 1)[0].lower().endswith(_IMAGE_SUFFIXES)


def _absolute(target: str, *, image: bool, ref: str) -> str:
    if image:
        return f"https://raw.githubusercontent.com/{REPOSITORY}/{ref}/{target}"
    return f"https://github.com/{REPOSITORY}/blob/{ref}/{target}"


def absolutize(text: str, ref: str) -> str:
    def rewrite(match: re.Match[str]) -> str:
        target = match["target"]
        if not _is_relative(target):
            return match[0]
        kind = match.groupdict().get("attr") or match.groupdict().get("bang", "")
        return match["lead"] + _absolute(target, image=_is_image(kind, target), ref=ref) + match["tail"]

    return _MARKDOWN.sub(rewrite, _HTML.sub(rewrite, text))


def relative_links(text: str) -> list[str]:
    targets = [match["target"] for match in _HTML.finditer(text)]
    targets += [match["target"] for match in _MARKDOWN.finditer(text)]
    return [target for target in targets if _is_relative(target)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("readme", type=Path)
    parser.add_argument("--ref", required=True, help="release tag the links should resolve against")
    args = parser.parse_args(argv)
    text = absolutize(args.readme.read_text(), args.ref)
    if re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", args.ref):
        text = re.sub(
            rf"^git clone --branch v\S+ --depth 1 https://github.com/{re.escape(REPOSITORY)}\.git$",
            lambda _: f"git clone --branch {args.ref} --depth 1 https://github.com/{REPOSITORY}.git",
            text,
            flags=re.MULTILINE,
        )
    args.readme.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
