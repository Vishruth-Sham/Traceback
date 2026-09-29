"""Backend-owned, pure voice-command policy.

No I/O, database, network, or clock access: transcript, timestamps, catalog,
`now`, and settings are passed in. The processor imports nothing from here; the
backend recomputes every fact from stored evidence, and tests exercise exactly
this production code.
"""
from backend.voice_policy.policy import POLICY_VERSION, evaluate

__all__ = ["POLICY_VERSION", "evaluate"]
