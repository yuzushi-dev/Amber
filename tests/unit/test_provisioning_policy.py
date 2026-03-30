from unittest.mock import MagicMock, patch

import pytest

from src.api.config import Settings
from src.core.admin_ops.application.provisioning_policy import (
    ProvisioningDisabledError,
    ensure_tenant_provisioning_enabled,
)


def test_settings_expose_fail_closed_provisioning_flag():
    fields = Settings.model_fields
    assert 'enable_tenant_provisioning' in fields
    assert fields['enable_tenant_provisioning'].default is False


def test_provisioning_policy_raises_when_disabled():
    mock = MagicMock()
    mock.enable_tenant_provisioning = False
    with patch("src.core.admin_ops.application.provisioning_policy.get_settings", return_value=mock):
        with pytest.raises(ProvisioningDisabledError) as exc:
            ensure_tenant_provisioning_enabled()

    assert 'disabled on this deployment' in str(exc.value)


def test_provisioning_policy_allows_when_enabled():
    mock = MagicMock()
    mock.enable_tenant_provisioning = True
    with patch("src.core.admin_ops.application.provisioning_policy.get_settings", return_value=mock):
        ensure_tenant_provisioning_enabled()
