from unittest.mock import patch

import pytest

from src.api.config import Settings
from src.api.config import settings as app_settings
from src.core.admin_ops.application.provisioning_policy import (
    ProvisioningDisabledError,
    ensure_tenant_provisioning_enabled,
)


def test_settings_expose_fail_closed_provisioning_flag():
    fields = Settings.model_fields
    assert 'enable_tenant_provisioning' in fields
    assert fields['enable_tenant_provisioning'].default is False


def test_provisioning_policy_raises_when_disabled():
    with patch.object(app_settings, 'enable_tenant_provisioning', False, create=True):
        with pytest.raises(ProvisioningDisabledError) as exc:
            ensure_tenant_provisioning_enabled()

    assert 'disabled on this deployment' in str(exc.value)


def test_provisioning_policy_allows_when_enabled():
    with patch.object(app_settings, 'enable_tenant_provisioning', True, create=True):
        ensure_tenant_provisioning_enabled()
