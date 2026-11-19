import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record):
        result = {"time": self.formatTime(record), "level": record.levelname, "event": record.getMessage()}
        for key in ("job_id", "source_name", "job_status"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        # Exception bodies and request headers are deliberately excluded.
        return json.dumps(result)
