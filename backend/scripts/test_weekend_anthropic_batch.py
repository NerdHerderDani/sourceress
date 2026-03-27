from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.weekend_jobs_model import WeekendJob, WeekendArtifact
from app.services.weekend_anthropic_batch_service import build_weekend_batch_payload


class WeekendAnthropicBatchTests(unittest.TestCase):
    def test_build_payload_includes_cache_control(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "uploads").mkdir(parents=True, exist_ok=True)
            p = root / "uploads" / "doc.txt"
            p.write_text("hello world", encoding="utf-8")

            job = WeekendJob(id=123, title="t", notes="n")
            art = WeekendArtifact(id=7, job_id=123, kind="upload", filename="doc.txt", rel_path="uploads/doc.txt")

            payload = build_weekend_batch_payload(
                job=job,
                artifacts=[art],
                root=root,
                model="claude-test",
                system_prompt="SYSTEM",
                max_tokens=55,
            )

            self.assertIn("requests", payload)
            self.assertEqual(len(payload["requests"]), 1)
            req = payload["requests"][0]
            self.assertEqual(req["custom_id"], "job123:artifact7")
            params = req["params"]
            self.assertEqual(params["model"], "claude-test")
            self.assertEqual(params["max_tokens"], 55)
            self.assertIsInstance(params.get("system"), list)
            self.assertEqual(params["system"][0]["cache_control"], {"type": "ephemeral"})


if __name__ == "__main__":
    unittest.main()
