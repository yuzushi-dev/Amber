"""
Tests for PR-10: Decouple Milvus from Garage storage.
"""
import pytest
import yaml


class TestMilvusDecouple:
    """Test that Milvus is configured for local storage (not Garage)."""

    def test_milvus_no_garage_env_vars(self):
        """Test that Milvus service does not use Garage S3 storage."""
        with open('/home/daniele/Amber/docker-compose.yml') as f:
            content = yaml.safe_load(f)

        milvus = content.get('services', {}).get('milvus', {})
        env = milvus.get('environment', [])

        # Convert to dict if list format
        env_dict = {}
        if isinstance(env, list):
            for item in env:
                if isinstance(item, str) and '=' in item:
                    key, val = item.split('=', 1)
                    env_dict[key] = val
        else:
            env_dict = env

        # Should not point to garage
        minio_addr = env_dict.get('MINIO_ADDRESS', '')
        assert 'garage' not in minio_addr, \
            "Milvus should not use Garage S3 storage (uses minio instead)"

        # Should still have ETCD
        assert 'ETCD_ENDPOINTS' in env_dict, \
            "Milvus should still have ETCD_ENDPOINTS"

    def test_milvus_has_volume_mount(self):
        """Test that Milvus has a volume mount for local storage."""
        with open('/home/daniele/Amber/docker-compose.yml') as f:
            content = yaml.safe_load(f)

        milvus = content.get('services', {}).get('milvus', {})
        volumes = milvus.get('volumes', [])

        assert any('milvus' in v for v in volumes), \
            "Milvus should have a volume mount for data persistence"

    def test_milvus_not_dependent_on_garage(self):
        """Test that Milvus service does not depend on garage."""
        with open('/home/daniele/Amber/docker-compose.yml') as f:
            content = yaml.safe_load(f)

        milvus = content.get('services', {}).get('milvus', {})
        depends_on = milvus.get('depends_on', [])

        # If depends_on is a list, check it's not there
        if isinstance(depends_on, list):
            assert 'garage' not in depends_on, \
                "Milvus should not depend on garage service"
        # If it's a dict, check keys
        elif isinstance(depends_on, dict):
            assert 'garage' not in depends_on, \
                "Milvus should not depend on garage service"

    def test_docker_compose_valid_yaml(self):
        """Test that docker-compose.yml is valid YAML."""
        with open('/home/daniele/Amber/docker-compose.yml') as f:
            try:
                yaml.safe_load(f)
            except yaml.YAMLError as e:
                pytest.fail(f"Invalid YAML: {e}")
