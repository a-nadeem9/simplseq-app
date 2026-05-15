import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "gui" / "static" / "css" / "app.css").read_text()
JS = (ROOT / "gui" / "static" / "js" / "app.js").read_text()


class FrontendRegressionTests(unittest.TestCase):
    def test_scrollable_tables_keep_sticky_headers_above_rows(self):
        self.assertIn("border-collapse: separate;", CSS)
        self.assertIn("border-spacing: 0;", CSS)
        self.assertRegex(CSS, r"\.table-wrap\s+th,\s*\.results-table-wrap\s+th\s*{[^}]*z-index:\s*2;")
        self.assertRegex(CSS, r"\.table-wrap\s+th,\s*\.results-table-wrap\s+th\s*{[^}]*background:\s*var\(--panel")

    def test_active_run_on_page_load_starts_polling(self):
        init_body = re.search(r"async function init\(\) \{(?P<body>.*?)\n\}", JS, re.S).group("body")
        self.assertRegex(init_body, r"if\s*\(status\?\.active\)\s*\{[^}]*selectTab\(\"run\"\);[^}]*startPolling\(\);")

    def test_polling_error_does_not_stop_known_active_run(self):
        refresh_body = re.search(r"async function refreshAllRunState\(\) \{(?P<body>.*?)\n\}", JS, re.S).group("body")
        self.assertIn("if (!isActiveStatus(lastRunStatus) && pollTimer)", refresh_body)

    def test_disk_running_state_keeps_polling_even_without_process_handle(self):
        refresh_body = re.search(r"async function refreshAllRunState\(\) \{(?P<body>.*?)\n\}", JS, re.S).group("body")
        self.assertIn("if (!active && !isActiveStatus(currentStatus) && pollTimer)", refresh_body)

    def test_native_picker_label_changes_after_dialog_opens(self):
        choose_body = re.search(r"async function chooseFastqFolder\(\) \{(?P<body>.*?)\n\}", JS, re.S).group("body")
        self.assertIn('text(button, "Opening...");', choose_body)
        self.assertIn('text(button, "Waiting...");', choose_body)

    def test_progress_updates_are_tweened_not_hard_set(self):
        self.assertIn("let displayedProgressPercent = 0;", JS)
        self.assertIn("function animateProgressTo(percent)", JS)
        self.assertIn("requestAnimationFrame", JS)
        render_body = re.search(r"function renderStages\(events, summary, state\) \{(?P<body>.*?)\n\}", JS, re.S).group("body")
        self.assertIn("animateProgressTo(percent);", render_body)

    def test_running_dot_uses_dedicated_smooth_animation(self):
        self.assertIn("@keyframes running-dot-pulse", CSS)
        self.assertRegex(CSS, r"\.pipeline-status\.is-running::before\s*{[^}]*animation:\s*running-dot-pulse")
        self.assertRegex(CSS, r"\.stage-list li\.running \.stage-dot\s*{[^}]*animation:\s*running-dot-pulse")
