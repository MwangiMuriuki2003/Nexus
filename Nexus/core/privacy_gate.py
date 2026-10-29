from typing import Callable, Optional

from Nexus.audit.logger import AuditLogger
from Nexus.models.nebius_client import NebiusClient

# Callback receives (reason, token_estimate) and returns True to approve.
ApprovalCallback = Callable[[str, int], bool]


class PrivacyGate:
    def __init__(self, settings, approval_callback: Optional[ApprovalCallback] = None):
        self.settings = settings
        # UI mode injects a modal-backed callback; headless leaves it None (deny).
        self.approval_callback = approval_callback
        # No API key means cloud bursts stay disabled instead of failing on startup.
        self.nebius = (
            NebiusClient(settings.nebius_api_key, settings.nebius_base_url)
            if settings.nebius_api_key
            else None
        )
        self.audit = AuditLogger(settings.audit_path)
        self.approved = False
        self.approval_timeout = 30  # seconds

    def request_approval(self, reason: str, token_estimate: int) -> bool:
        """Ask whether this cloud request may leave the device.

        Headless (no callback): always denies and records the denial explicitly.
        Qt mode: `MainWindow` injects a callback that opens a modal showing the
        reason, token estimate and model name with Once/Session/Always choices;
        the modal blocks for at most `approval_timeout` seconds and defaults to
        deny. A session/always approval sets `self.approved`, which short-circuits
        later requests.

        Returns True only when the user explicitly approves.
        """
        if self.approved:
            return True

        if self.approval_callback is None:
            print(f"[Privacy Gate] Cloud request DENIED (headless, no approval UI): {reason}")
            self._log_approval_decision(reason, token_estimate, approved=False)
            return False

        try:
            approved = bool(self.approval_callback(reason, token_estimate))
        except Exception as exc:  # a broken modal must fail closed
            print(f"[Privacy Gate] Approval callback failed ({exc}); defaulting to deny.")
            approved = False

        if not approved:
            self._log_approval_decision(reason, token_estimate, approved=False)
        return approved

    def _log_approval_decision(self, reason: str, token_estimate: int, approved: bool) -> None:
        """Record the approval decision itself in the append-only audit log."""
        status = "approved" if approved else "denied"
        self.audit.log(
            action="cloud_approval",
            detail=f"{status}: reason={reason}, tokens_estimate={token_estimate}",
            risk_level="low",
        )

    def cloud_request(self, messages: list[dict], reason: str):
        """Process a cloud request through the privacy gate.
        
        1. Request user approval
        2. If approved, log and forward to Nebius
        3. If denied, handle locally with disclaimer
        """
        token_estimate = len(str(messages))
        approved = self.request_approval(reason, token_estimate)
        
        if approved:
            self.log_cloud_request(reason, token_estimate=token_estimate)
            if self.nebius is None:
                return {
                    "role": "assistant",
                    "content": (
                        "[Local] No Nebius API key configured. "
                        "Set NEXUS_NEBIUS_API_KEY to enable cloud bursts."
                    ),
                }
            return self.nebius.chat(messages)
        else:
            # Default to local processing with disclaimer
            self.log_cloud_request(reason, token_estimate=token_estimate, risk_level="medium")
            return {
                "role": "assistant",
                "content": f"[Local] Request denied by privacy gate. Reason: {reason}. Running local inference instead."
            }

    def log_cloud_request(self, reason: str, token_estimate: int, risk_level: str = "low"):
        """Append-only audit log for cloud requests."""
        self.audit.log(
            action="cloud_request",
            detail=f"reason={reason}, tokens_estimate={token_estimate}, risk={risk_level}",
            risk_level=risk_level,
        )

    def log_skill_execution(self, skill_name: str, exit_code: int, runtime: float):
        """Log skill execution to audit."""
        self.audit.log(
            action="skill_exec",
            detail=f"skill={skill_name}, exit_code={exit_code}, runtime={runtime:.2f}s",
            risk_level="low",
        )

    def log_memory_access(self, query: str, n_results: int):
        """Log memory access query to audit."""
        self.audit.log(
            action="memory_access",
            detail=f"query='{query[:50]}...', results={n_results}",
            risk_level="low",
        )
