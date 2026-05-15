from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import flask_app


class FolderPickerTests(unittest.TestCase):
    def test_macos_picker_returns_posix_path(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["osascript"],
            returncode=0,
            stdout="/Users/adina/Desktop/fastqs/\n",
            stderr="",
        )
        with (
            patch.object(flask_app.sys, "platform", "darwin"),
            patch.object(flask_app, "safe_exists", return_value=True),
            patch.object(flask_app.subprocess, "run", return_value=completed) as run,
        ):
            result = flask_app.select_folder_dialog(Path("/Users/adina/Desktop/fastqs"))

        self.assertEqual(result, {"ok": True, "selected": True, "path": "/Users/adina/Desktop/fastqs"})
        command = run.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertEqual(command[-2:], ["--", "/Users/adina/Desktop/fastqs"])

    def test_macos_picker_treats_cancel_as_no_selection(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["osascript"],
            returncode=1,
            stdout="",
            stderr="execution error: User canceled. (-128)\n",
        )
        with (
            patch.object(flask_app.sys, "platform", "darwin"),
            patch.object(flask_app.subprocess, "run", return_value=completed),
        ):
            result = flask_app.select_folder_dialog()

        self.assertEqual(result, {"ok": True, "selected": False})

    def test_wsl_picker_converts_windows_path(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["powershell.exe"],
            returncode=0,
            stdout="C:\\Users\\adina\\Desktop\\fastqs\r\n",
            stderr="",
        )
        with (
            patch.object(flask_app.sys, "platform", "linux"),
            patch.object(flask_app, "is_wsl", return_value=True),
            patch.object(flask_app.subprocess, "run", return_value=completed) as run,
        ):
            result = flask_app.select_folder_dialog()

        self.assertEqual(result["path"], "/mnt/c/Users/adina/Desktop/fastqs")
        self.assertEqual(result["windows_path"], "C:\\Users\\adina\\Desktop\\fastqs")
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")

    def test_non_native_platform_reports_fallback_error(self) -> None:
        with (
            patch.object(flask_app.sys, "platform", "linux"),
            patch.object(flask_app, "is_wsl", return_value=False),
        ):
            result = flask_app.select_folder_dialog()

        self.assertFalse(result["ok"])
        self.assertIn("WSL or macOS", result["error"])


if __name__ == "__main__":
    unittest.main()
