"""Provisioning policy guards for legacy tenant cloning paths."""

from src.shared.kernel.runtime import get_settings


class ProvisioningDisabledError(RuntimeError):
    """Raised when legacy tenant provisioning is disabled by policy."""


def provisioning_disabled_message() -> str:
    return (
        "Legacy tenant provisioning is disabled on this deployment. "
        "This path physically duplicates documents, chunks, vectors, and optional graph data. "
        "Use shared-document visibility and multi-scope retrieval instead. "
        "Only re-enable with ENABLE_TENANT_PROVISIONING=true for controlled migration or recovery work."
    )


def ensure_tenant_provisioning_enabled() -> None:
    if get_settings().enable_tenant_provisioning:
        return
    raise ProvisioningDisabledError(provisioning_disabled_message())
