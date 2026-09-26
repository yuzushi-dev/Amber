"""Regression guard: the API-key group lookup must run inside an RLS tenant context.

group_members is FORCE-RLS by tenant. Without a transaction-local
app.current_tenant on the lookup session, a fresh pooled connection returns
no groups, so group-enforced keys see zero documents.
"""

import inspect

from src.api.middleware.auth import AuthenticationMiddleware


def test_group_lookup_sets_transaction_local_tenant_before_select():
    src = inspect.getsource(AuthenticationMiddleware)
    lookup = src[src.index("_grp_session:"):]
    set_config = lookup.index("set_config('app.current_tenant', :tenant, true)")
    select_members = lookup.index("select(GroupMember.group_id)")
    assert set_config < select_members
