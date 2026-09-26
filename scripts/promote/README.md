# Promotion boundary — implementation pending

Promotion requires all schema, point-in-time, tool, grounding, and regression gates,
not just the offline structural score. Persist the complete candidate deployment
in the existing platform registry, switch the active reference atomically, restart
inference, and verify readiness. Retain the previous deployment for rollback.
The current CLI always reports `promotion_eligible: false`; it cannot promote.
