# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks for new upstream Go releases and files a tracking bug when found."""

import argparse
import dataclasses
import json
import logging
from pathlib import Path
import re
from typing import Self
import urllib.request

from cros_utils import bugs
from llvm_tools import atomic_write_file


GO_RELEASES_JSON_URL = "https://go.dev/dl/?mode=json"

# Matches e.g. "go1.27.3", "1.27.3", or "go1.20".
_VERSION_STRING_RE = re.compile(r"^(?:go)?(\d+)\.(\d+)(?:\.(\d+))?$")


@dataclasses.dataclass(frozen=True, order=True)
class GoReleaseVersion:
    """Represents a version of Go's stable compiler."""

    major: int
    minor: int
    patch: int

    @classmethod
    def from_string(cls, version_string: str) -> Self:
        """Parses a Go version string like 'go1.27.3', '1.27.3', or 'go1.20'.

        Missing patch versions default to 0.
        """
        m = _VERSION_STRING_RE.match(version_string)
        if not m:
            raise ValueError(
                f"{version_string!r} isn't a valid Go version string"
            )
        return cls(
            major=int(m.group(1)),
            minor=int(m.group(2)),
            patch=int(m.group(3)) if m.group(3) else 0,
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclasses.dataclass(frozen=True)
class GoRelease:
    """Represents an upstream Go stable release and its source archive."""

    version: GoReleaseVersion
    src_sha256: str


def parse_releases_json_blob(payload: str) -> list[GoRelease]:
    """Parses the JSON payload from https://go.dev/dl/?mode=json."""
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError(
            f"Expected JSON list of releases from {GO_RELEASES_JSON_URL}"
        )

    releases: list[GoRelease] = []
    for entry in parsed:
        if not entry["stable"]:
            continue
        version = GoReleaseVersion.from_string(entry["version"])
        src_sha256 = next(
            (
                f["sha256"]
                for f in entry.get("files", ())
                if f.get("kind") == "source" and f.get("sha256")
            ),
            None,
        )
        if not src_sha256:
            raise ValueError(f"No source sha256 found for Go {version}")
        releases.append(GoRelease(version=version, src_sha256=src_sha256))
    return releases


def parse_most_recent_release(payload: str) -> GoRelease:
    """Returns the newest stable `GoRelease` from a JSON payload."""
    releases = parse_releases_json_blob(payload)
    if not releases:
        raise ValueError(
            f"No stable Go releases found in {GO_RELEASES_JSON_URL} response"
        )
    return max(releases, key=lambda r: r.version)


def fetch_most_recent_release() -> GoRelease:
    """Queries go.dev for the most recent stable Go release."""
    logging.debug("Querying %s", GO_RELEASES_JSON_URL)
    with urllib.request.urlopen(GO_RELEASES_JSON_URL, timeout=30) as response:
        payload = response.read().decode("utf-8")
    return parse_most_recent_release(payload)


def read_state(state_file: Path) -> GoReleaseVersion:
    """Reads the last seen release from the given state file."""
    with state_file.open(encoding="utf-8") as f:
        data = json.load(f)
    return GoReleaseVersion.from_string(data["last_seen_release"])


def atomically_write_state(
    state_file: Path, last_seen_release: GoReleaseVersion
) -> None:
    """Atomically writes the last seen release to the given state file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write_file.atomic_write(state_file, encoding="utf-8") as f:
        json.dump({"last_seen_release": str(last_seen_release)}, f)


def maybe_compose_bug(
    last_seen_release: GoReleaseVersion,
    newest_release: GoRelease,
) -> tuple[str, str] | None:
    """Creates a bug to file about the new release, if a newer one exists."""
    if newest_release.version <= last_seen_release:
        return None

    version = newest_release.version
    title = f"[ChromeOS/Go] Update to {version}"
    body = "\n\n".join(
        (
            f"Go {version} has been released upstream on https://go.dev/dl/; "
            "we should probably roll to it.",
            f"Upstream source archive (`go{version}.src.tar.gz`) SHA256: "
            f"`{newest_release.src_sha256}`",
            "See http://go/crostc-go-on-chromeos for the upgrade steps.",
            "For questions about this bot, please contact "
            "chromeos-toolchain@ and CC gbiv@.",
        )
    )
    return title, body


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        required=True,
        help="Path to the JSON state file tracking the last seen Go release.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without filing a bug or updating state.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    """Entry point."""
    opts = parse_args(argv)
    logging.basicConfig(
        format=">> %(asctime)s: %(levelname)s: %(filename)s:%(lineno)d: "
        "%(message)s",
        level=logging.DEBUG if opts.debug else logging.INFO,
    )

    state_file: Path = opts.state_file
    newest_release = fetch_most_recent_release()
    logging.info("Most recent Go release is %s", newest_release.version)

    try:
        last_seen_release = read_state(state_file)
    except FileNotFoundError:
        if opts.dry_run:
            logging.info(
                "State file %s does not exist; dry run would write initial "
                "state for Go %s.",
                state_file,
                newest_release.version,
            )
            return
        logging.info(
            "State file %s does not exist; writing initial state for Go %s.",
            state_file,
            newest_release.version,
        )
        atomically_write_state(state_file, newest_release.version)
        return

    logging.info("Last seen release was %s", last_seen_release)

    maybe_bug = maybe_compose_bug(last_seen_release, newest_release)
    if not maybe_bug:
        logging.info("No newer Go release detected; nothing to do.")
        return

    bug_title, bug_body = maybe_bug
    if opts.dry_run:
        logging.info(
            "Dry run; skipping filing bug with title %r and contents:\n%s",
            bug_title,
            bug_body,
        )
        return

    logging.info("Filing new bug: %s", bug_title)
    bugs.CreateNewBug(
        component_id=bugs.WellKnownComponents.CrOSToolchainPrivate,
        title=bug_title,
        body=bug_body,
        assignee="gbiv@google.com",
    )
    atomically_write_state(state_file, newest_release.version)
