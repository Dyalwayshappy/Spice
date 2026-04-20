from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from spice_hermes_bridge.extraction.proposals import CommitmentProposal


class CommitmentProposalProvider(Protocol):
    def propose_commitment(
        self,
        *,
        text: str,
        reference_time: datetime | None,
        default_timezone: str,
    ) -> CommitmentProposal | None:
        """Return a structured proposal. Providers must not emit observations."""


@dataclass(frozen=True, slots=True)
class CommandLLMCommitmentProvider:
    command: str
    timeout_seconds: int = 20

    def propose_commitment(
        self,
        *,
        text: str,
        reference_time: datetime | None,
        default_timezone: str,
    ) -> CommitmentProposal | None:
        payload = {
            "task": "extract_commitment_proposal",
            "rules": {
                "proposal_only": True,
                "do_not_decide_importance": True,
                "do_not_update_state": True,
                "do_not_detect_conflicts": True,
                "do_not_trigger_decisions": True,
                "do_not_guess_precise_times": True,
            },
            "text": text,
            "reference_time": reference_time.isoformat() if reference_time else None,
            "default_timezone": default_timezone,
            "expected_output": {
                "summary": "string or null",
                "start_time": "ISO-8601 with timezone or null",
                "end_time": "ISO-8601 with timezone or null",
                "duration_minutes": "integer or null",
                "prep_start_time": "ISO-8601 with timezone or null",
                "priority_hint": "string or null",
                "flexibility_hint": "string or null",
                "constraint_hints": ["string"],
                "meta": {
                    "confidence": "0..1",
                    "uncertain_fields": ["field"],
                    "assumptions": ["assumption"],
                    "needs_confirmation": "boolean",
                },
            },
        }

        completed = subprocess.run(
            shlex.split(self.command),
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "LLM command failed")

        decoded = json.loads(completed.stdout)
        if not isinstance(decoded, dict):
            raise ValueError("LLM proposal output must be a JSON object")
        return CommitmentProposal.from_payload(decoded, extractor="llm_assisted")


def provider_from_environment() -> CommitmentProposalProvider | None:
    command = os.environ.get("SPICE_HERMES_LLM_COMMAND")
    if not command:
        return None
    return CommandLLMCommitmentProvider(command=command)
