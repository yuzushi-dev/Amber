
from src.core.tenants.application.query_scopes import QueryScopes, resolve_query_scopes


def test_default_tenant_scopes_are_local_only():
    scopes = resolve_query_scopes("default")

    assert isinstance(scopes, QueryScopes)
    assert scopes.effective_tenant_id == "default"
    assert scopes.vector_scopes == ["default"]
    assert scopes.graph_scopes == ["default"]
    assert scopes.shared_document_owner_tenants == ["default"]


def test_non_default_tenant_scopes_include_default_and_self():
    scopes = resolve_query_scopes("engineering")

    assert scopes.effective_tenant_id == "engineering"
    assert scopes.vector_scopes == ["default", "engineering"]
    assert scopes.graph_scopes == ["default", "engineering"]
    assert scopes.shared_document_owner_tenants == ["default"]


def test_query_scopes_do_not_duplicate_default():
    scopes = resolve_query_scopes("default")
    assert scopes.vector_scopes.count("default") == 1
    assert scopes.graph_scopes.count("default") == 1
