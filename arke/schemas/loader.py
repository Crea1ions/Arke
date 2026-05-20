"""Load and validate Themelios-Archè data contracts."""

import json
from pathlib import Path
from typing import Any, Dict

import jsonschema
import structlog

log = structlog.get_logger()

_SCHEMA_DIR = Path(__file__).parent


class ContractValidator:
    """Thread data contract validator (permissive: warn, not reject)."""

    def __init__(self):
        """Load schemas from JSON files."""
        self.thread_schema = json.loads(
            (_SCHEMA_DIR / "thread_contract.json").read_text()
        )
        self.enrichment_schema = json.loads(
            (_SCHEMA_DIR / "enrichment_contract.json").read_text()
        )
        self.contract_version = self.thread_schema["version"]

    def validate_thread(self, thread: Dict[str, Any]) -> bool:
        """Validate thread against Themelios contract (permissive)."""
        try:
            jsonschema.validate(thread, self.thread_schema)
            return True
        except jsonschema.ValidationError as e:
            log.warning(
                "thread_contract_violation",
                error=str(e),
                thread_id=thread.get("thread_id"),
            )
            return False

    def validate_enrichment(self, enrichment: Dict[str, Any]) -> bool:
        """Validate enrichment against Archè contract (permissive)."""
        try:
            jsonschema.validate(enrichment, self.enrichment_schema)
            return True
        except jsonschema.ValidationError as e:
            log.warning("enrichment_contract_violation", error=str(e))
            return False


# Global instance
_validator = None


def get_validator() -> ContractValidator:
    """Get or create global validator instance."""
    global _validator
    if _validator is None:
        _validator = ContractValidator()
    return _validator
