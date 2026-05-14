import json
import tempfile
import unittest
from pathlib import Path

from gui.flask_app import create_app


class FlaskStatusTests(unittest.TestCase):
    def test_stale_running_state_is_not_reported_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            outdir = workspace / "results"
            outdir.mkdir()
            (outdir / "run_state.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
            (outdir / "progress.jsonl").write_text(
                json.dumps({"stage": "dada2", "status": "running", "user_visible": True}) + "\n",
                encoding="utf-8",
            )

            app = create_app(Path.cwd(), workspace)

            response = app.test_client().get("/api/status?out=results")
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertFalse(payload["active"])
            self.assertEqual(payload["state"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
