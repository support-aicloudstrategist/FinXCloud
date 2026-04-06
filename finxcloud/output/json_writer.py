"""JSON output writer for FinXCloud AWS cost optimization reports."""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class JSONWriter:
    """Write report dicts to JSON files."""

    def __init__(self, output_dir: str = "reports") -> None:
        self.output_dir = output_dir

    def write(self, report: dict, filename: str) -> str:
        """Write a single report dict to a JSON file.

        Creates *output_dir* if it does not exist.  Returns the absolute
        path to the written file.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        file_path = str(Path(self.output_dir) / filename)

        log.info("Writing JSON report to %s", file_path)
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)

        log.info("JSON report written: %s", file_path)
        return file_path

    def write_all(
        self,
        detailed: dict,
        summary: dict,
        roadmap: dict,
    ) -> list[str]:
        """Write all three standard reports and return their file paths."""
        paths: list[str] = [
            self.write(detailed, "detailed_report.json"),
            self.write(summary, "summary_report.json"),
            self.write(roadmap, "roadmap_report.json"),
        ]
        log.info("All JSON reports written (%d files)", len(paths))
        return paths
