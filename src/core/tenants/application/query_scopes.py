"""
Query Scope Resolution
======================

Central resolver for the tenant scopes a request is allowed to query.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_TENANT_ID = "default"


@dataclass(frozen=True)
class QueryScopes:
    """Resolved data scopes for a request."""

    effective_tenant_id: str
    vector_scopes: list[str]
    graph_scopes: list[str]
    shared_document_owner_tenants: list[str]
    group_ids: list[str] = field(default_factory=list)
    enforce_groups: bool = field(default=False)


def resolve_query_scopes(
    tenant_id: str,
    group_ids: list[str] | None = None,
    enforce_groups: bool = False,
) -> QueryScopes:
    """Resolve the allowed query scopes for a tenant.

    Current policy:
    - default queries only default
    - non-default tenants query default + self
    - no child tenant can query other child tenants

    ``group_ids`` and ``enforce_groups`` carry the caller's group membership and
    the tenant's group-enforcement flag into the scopes object so retrieval can
    apply the same group ACL the direct document endpoints enforce. They MUST be
    threaded through by the caller (auth middleware); the defaults keep group
    enforcement off for callers that have no group context.
    """
    normalized_tenant_id = str(tenant_id or DEFAULT_TENANT_ID)
    _groups = list(group_ids or [])

    if normalized_tenant_id == DEFAULT_TENANT_ID:
        return QueryScopes(
            effective_tenant_id=DEFAULT_TENANT_ID,
            vector_scopes=[DEFAULT_TENANT_ID],
            graph_scopes=[DEFAULT_TENANT_ID],
            shared_document_owner_tenants=[DEFAULT_TENANT_ID],
            group_ids=_groups,
            enforce_groups=enforce_groups,
        )

    return QueryScopes(
        effective_tenant_id=normalized_tenant_id,
        vector_scopes=_dedupe([DEFAULT_TENANT_ID, normalized_tenant_id]),
        graph_scopes=_dedupe([DEFAULT_TENANT_ID, normalized_tenant_id]),
        shared_document_owner_tenants=[DEFAULT_TENANT_ID],
        group_ids=_groups,
        enforce_groups=enforce_groups,
    )


def resolve_super_admin_query_scopes(all_tenant_ids: list[str]) -> QueryScopes:
    """Resolve query scopes for a super-admin request.

    Super-admin sees all tenants: every tenant's vectors and graph nodes
    are included in the search, with no ACL filtering across scopes.
    """
    scopes = _dedupe([DEFAULT_TENANT_ID] + [t for t in all_tenant_ids if t != DEFAULT_TENANT_ID])
    return QueryScopes(
        effective_tenant_id=DEFAULT_TENANT_ID,
        vector_scopes=scopes,
        graph_scopes=scopes,
        shared_document_owner_tenants=scopes,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered
