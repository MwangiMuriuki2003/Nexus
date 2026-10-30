from typing import Callable, Optional

from Nexus.audit.logger import AuditLogger
from Nexus.keys import resolve_cloud_config
from Nexus.models.nebius_client import NebiusClient

# Callback receives (reason, token_estimate) and returns True to approve.
ApprovalCallback = Callable[[str, int], bool]


def estimate_tokens(text: str) -> int:
    """Approximate token count as `len(text) / 4`.

    Documented approximation rather than a tokenizer dependency: the number
    only sizes a user-facing approval prompt ("~N tokens will leave this
    device"), where being within ~2x is fine. It is never used for billing,
    truncation or context-window math.
    """
    return max(1, len(text) // 4)


class PrivacyGate:
    def __init__(self, settings, approval_callback: Optional[ApprovalCallback] = None):
        self.settings = settings
        # UI mode injects a modal-backed callback; headless leaves it None (deny).
        self.approval_callback = approval_callback
        self.audit = AuditLogger(settings.audit_path)
        self.approved = False
        self.approval_timeout = 30  # seconds
        # No API key (saved in Settings or set via env) means cloud bursts stay
        # disabled instead of failing on startup.
        self.refresh_config()

    def refresh_config(self) -> None:
        """Re-read the bring-your-own key and endpoint prefs from disk.

        Called at construction and again whenever Settings change, so a key or
        base URL saved while the app is running is used by the very next cloud
        request — no restart, no engine rebuild.
        """
        config = resolve_cloud_config(self.settings)
        self.cloud_config = config
        self.nebius = (
            NebiusClient(config.api_key, config.base_url) if config.api_key else None
        )

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
        token_estimate = estimate_tokens(str(messages))
        approved = self.request_approval(reason, token_estimate)
        
        if approved:
            self.log_cloud_request(reason, token_estimate=token_estimate, approved=True)
            if self.nebius is None:
                return {
                    "role": "assistant",
                    "content": (
                        "[Local] No Nebius API key configured. "
                        "Add your own key in Settings (or set NEXUS_NEBIUS_API_KEY) "
                        "to enable cloud bursts."
                    ),
                }
            return self.nebius.chat(messages, model=self.cloud_config.model)
        else:
            # Default to local processing with disclaimer
            self.log_cloud_request(reason, token_estimate=token_estimate, approved=False)
            return {
                "role": "assistant",
                "content": f"[Local] Request denied by privacy gate. Reason: {reason}. Running local inference instead."
            }

    def log_cloud_request(self, reason: str, token_estimate: int, approved: bool = False):
        """Append-only audit log for cloud requests.

        Risk follows where the data went: approved means payloads left the
        device ("high"); denied means a local fallback only ("low").
        """
        status = "approved" if approved else "denied"
        self.audit.log(
            action="cloud_request",
            detail=f"{status}: reason={reason}, tokens_estimate={token_estimate}",
            risk_level="high" if approved else "low",
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
