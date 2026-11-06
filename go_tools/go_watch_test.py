# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for go_watch.py."""

import json
from unittest import mock

from cros_utils import bugs
from go_tools import go_watch
from llvm_tools import test_helpers


class Test(test_helpers.TempDirTestCase):
    """Tests for go_watch."""

    def test_release_version_parsing(self) -> None:
        self.assertEqual(
            go_watch.GoReleaseVersion.from_string("go1.27.3"),
            go_watch.GoReleaseVersion(1, 27, 3),
        )
        self.assertEqual(
            go_watch.GoReleaseVersion.from_string("1.27.3"),
            go_watch.GoReleaseVersion(1, 27, 3),
        )
        self.assertEqual(
            go_watch.GoReleaseVersion.from_string("go1.20"),
            go_watch.GoReleaseVersion(1, 20, 0),
        )
        self.assertEqual(
            go_watch.GoReleaseVersion.from_string("1.20"),
            go_watch.GoReleaseVersion(1, 20, 0),
        )
        with self.assertRaises(ValueError):
            go_watch.GoReleaseVersion.from_string("go1.28rc1")

    def test_parse_releases_json_blob_filters_and_extracts_source_sha256(
        self,
    ) -> None:
        payload = json.dumps(
            [
                {
                    "version": "go1.28rc1",
                    "stable": False,
                    "files": [
                        {
                            "filename": "go1.28rc1.src.tar.gz",
                            "kind": "source",
                            "sha256": "rc_sha256",
                        },
                    ],
                },
                {
                    "version": "go1.27.3",
                    "stable": True,
                    "files": [
                        {
                            "filename": "go1.27.3.linux-amd64.tar.gz",
                            "kind": "archive",
                            "sha256": "binary_sha256",
                        },
                        {
                            "filename": "go1.27.3.src.tar.gz",
                            "kind": "source",
                            "sha256": "src_sha256_1273",
                        },
                    ],
                },
                {
                    "version": "go1.26.10",
                    "stable": True,
                    "files": [
                        {
                            "filename": "go1.26.10.src.tar.gz",
                            "kind": "source",
                            "sha256": "src_sha256_12610",
                        },
                    ],
                },
                {
                    "version": "go1.20",
                    "stable": True,
                    "files": [
                        {
                            "filename": "go1.20.src.tar.gz",
                            "kind": "source",
                            "sha256": "src_sha256_1200",
                        },
                    ],
                },
            ]
        )

        releases = go_watch.parse_releases_json_blob(payload)
        self.assertEqual(
            releases,
            [
                go_watch.GoRelease(
                    version=go_watch.GoReleaseVersion(1, 27, 3),
                    src_sha256="src_sha256_1273",
                ),
                go_watch.GoRelease(
                    version=go_watch.GoReleaseVersion(1, 26, 10),
                    src_sha256="src_sha256_12610",
                ),
                go_watch.GoRelease(
                    version=go_watch.GoReleaseVersion(1, 20, 0),
                    src_sha256="src_sha256_1200",
                ),
            ],
        )
        self.assertEqual(
            go_watch.parse_most_recent_release(payload),
            go_watch.GoRelease(
                version=go_watch.GoReleaseVersion(1, 27, 3),
                src_sha256="src_sha256_1273",
            ),
        )

        # Stable entry with invalid version or missing source sha256 raises:
        with self.assertRaises(ValueError):
            go_watch.parse_releases_json_blob(
                json.dumps(
                    [{"version": "go1.28beta1", "stable": True, "files": []}]
                )
            )
        with self.assertRaisesRegex(ValueError, "No source sha256 found"):
            go_watch.parse_releases_json_blob(
                json.dumps(
                    [{"version": "go1.27.3", "stable": True, "files": []}]
                )
            )

    def test_parse_most_recent_release_fails_when_no_stable_versions(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "No stable Go releases found"):
            go_watch.parse_most_recent_release(
                json.dumps([{"version": "go1.28rc1", "stable": False}])
            )
        with self.assertRaisesRegex(ValueError, "Expected JSON list"):
            go_watch.parse_most_recent_release(
                json.dumps({"version": "go1.27.3"})
            )

    @mock.patch.object(bugs, "CreateNewBug", autospec=True)
    @mock.patch.object(go_watch, "fetch_most_recent_release", autospec=True)
    def test_main_initializes_missing_state_file_without_filing_bug(
        self,
        mock_fetch: mock.MagicMock,
        mock_create_bug: mock.MagicMock,
    ) -> None:
        mock_fetch.return_value = go_watch.GoRelease(
            version=go_watch.GoReleaseVersion(1, 27, 3),
            src_sha256="abc123",
        )
        state_file = self.make_tempdir() / "nested" / "dir" / "state.json"
        go_watch.main([f"--state-file={state_file}"])

        self.assertTrue(state_file.exists())
        self.assertEqual(
            go_watch.read_state(state_file),
            go_watch.GoReleaseVersion(1, 27, 3),
        )
        mock_create_bug.assert_not_called()

    @mock.patch.object(bugs, "CreateNewBug", autospec=True)
    @mock.patch.object(go_watch, "fetch_most_recent_release", autospec=True)
    def test_main_no_op_when_version_unchanged_or_older(
        self,
        mock_fetch: mock.MagicMock,
        mock_create_bug: mock.MagicMock,
    ) -> None:
        state_file = self.make_tempdir() / "state.json"
        initial_version = go_watch.GoReleaseVersion(1, 27, 3)
        go_watch.atomically_write_state(state_file, initial_version)

        # Same version:
        mock_fetch.return_value = go_watch.GoRelease(
            version=go_watch.GoReleaseVersion(1, 27, 3),
            src_sha256="abc123",
        )
        go_watch.main([f"--state-file={state_file}"])
        mock_create_bug.assert_not_called()
        self.assertEqual(go_watch.read_state(state_file), initial_version)

        # Older minor branch backport:
        mock_fetch.return_value = go_watch.GoRelease(
            version=go_watch.GoReleaseVersion(1, 26, 11),
            src_sha256="def456",
        )
        go_watch.main([f"--state-file={state_file}"])
        mock_create_bug.assert_not_called()
        self.assertEqual(go_watch.read_state(state_file), initial_version)

    @mock.patch.object(bugs, "CreateNewBug", autospec=True)
    @mock.patch.object(go_watch, "fetch_most_recent_release", autospec=True)
    def test_main_files_bug_and_updates_state_on_newer_release(
        self,
        mock_fetch: mock.MagicMock,
        mock_create_bug: mock.MagicMock,
    ) -> None:
        state_file = self.make_tempdir() / "state.json"
        go_watch.atomically_write_state(
            state_file,
            go_watch.GoReleaseVersion(1, 27, 2),
        )
        mock_fetch.return_value = go_watch.GoRelease(
            version=go_watch.GoReleaseVersion(1, 27, 3),
            src_sha256="6e7749035cf360f0",
        )

        go_watch.main([f"--state-file={state_file}"])

        mock_create_bug.assert_called_once()
        call_kwargs = mock_create_bug.call_args.kwargs
        self.assertEqual(
            call_kwargs["component_id"],
            bugs.WellKnownComponents.CrOSToolchainPrivate,
        )
        self.assertEqual(call_kwargs["title"], "[ChromeOS/Go] Update to 1.27.3")
        self.assertEqual(call_kwargs["assignee"], "gbiv@google.com")
        self.assertIn(
            "Go 1.27.3 has been released upstream", call_kwargs["body"]
        )
        self.assertIn("`go1.27.3.src.tar.gz`", call_kwargs["body"])
        self.assertIn("`6e7749035cf360f0`", call_kwargs["body"])
        self.assertIn("go/crostc-go-on-chromeos", call_kwargs["body"])
        self.assertEqual(
            go_watch.read_state(state_file),
            go_watch.GoReleaseVersion(1, 27, 3),
        )

    @mock.patch.object(bugs, "CreateNewBug", autospec=True)
    @mock.patch.object(go_watch, "fetch_most_recent_release", autospec=True)
    def test_main_respects_dry_run(
        self,
        mock_fetch: mock.MagicMock,
        mock_create_bug: mock.MagicMock,
    ) -> None:
        state_file = self.make_tempdir() / "state.json"
        mock_fetch.return_value = go_watch.GoRelease(
            version=go_watch.GoReleaseVersion(1, 27, 3),
            src_sha256="6e7749035cf360f0",
        )

        # Dry run with missing state file does not create it:
        go_watch.main([f"--state-file={state_file}", "--dry-run"])
        self.assertFalse(state_file.exists())
        mock_create_bug.assert_not_called()

        # Dry run with existing state neither files bug nor updates state:
        initial_version = go_watch.GoReleaseVersion(1, 27, 2)
        go_watch.atomically_write_state(state_file, initial_version)
        go_watch.main([f"--state-file={state_file}", "--dry-run"])

        mock_create_bug.assert_not_called()
        self.assertEqual(go_watch.read_state(state_file), initial_version)
