"""
Setup Service
=============

Manages on-demand installation of optional ML dependencies.
Provides feature detection, async installation, and status tracking.
"""

import asyncio
import importlib
import logging
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import metadata, util
from typing import Any

logger = logging.getLogger(__name__)


class FeatureStatus(StrEnum):
    """Installation status for optional features."""

    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"


@dataclass
class Feature:
    """Optional feature definition."""

    id: str
    name: str
    description: str
    packages: list[str]
    size_mb: int
    check_import: str  # Module to import to verify installation
    pip_extra_args: list[str] = field(default_factory=list)
    status: FeatureStatus = FeatureStatus.NOT_INSTALLED
    error_message: str | None = None


# Each optional feature is resolved in an independent pip invocation into the
# same target directory. Repeat this shared constraint in every ML feature that
# can otherwise resolve a newer, OpenTelemetry-incompatible Protobuf release.
OPTIONAL_PROTOBUF_PIN = "protobuf==6.33.6"
FRESH_PACKAGES_VOLUME_REQUIRED = (
    "Installed optional packages do not match the validated versions. "
    "Select a fresh versioned PACKAGES_DIR volume; the active volume was not modified."
)


# Define all optional features
OPTIONAL_FEATURES: dict[str, Feature] = {
    "local_embeddings": Feature(
        id="local_embeddings",
        name="Local Embeddings",
        description="Generate embeddings locally (Est. ~5 mins)",
        packages=[
            "torch==2.13.0+cpu",
            "sentence-transformers==5.6.1",
            "transformers==5.14.1",
            "huggingface-hub==1.25.1",
            "tokenizers==0.22.2",
            OPTIONAL_PROTOBUF_PIN,
        ],
        size_mb=2100,
        check_import="sentence_transformers",
        pip_extra_args=["--extra-index-url", "https://download.pytorch.org/whl/cpu"],
    ),
    "reranking": Feature(
        id="reranking",
        name="FlashRank Reranking",
        description="High-quality result reranking (Est. <1 min)",
        packages=["flashrank>=0.2.0", OPTIONAL_PROTOBUF_PIN],
        size_mb=50,
        check_import="flashrank",
    ),
    "community_detection": Feature(
        id="community_detection",
        name="Community Detection",
        description="Leiden algorithm for community analysis (Est. ~1 min)",
        packages=["cdlib>=0.3.0", "leidenalg>=0.10.0", "python-igraph>=0.11.0"],
        size_mb=150,
        check_import="leidenalg",
    ),
    "document_processing": Feature(
        id="document_processing",
        name="Document Processing",
        description="Parse PDFs, DOCX, HTML (Est. ~2 mins)",
        packages=[
            "unstructured[docx]>=0.18.31",
            "python-magic>=0.4.27",
            "pymupdf4llm>=0.0.1",
            "Pillow>=12.3.0",
            "pi-heif>=1.3.0",
        ],
        size_mb=800,
        check_import="unstructured",
    ),
    "ragas": Feature(
        id="ragas",
        name="RAGAS Evaluation",
        description="Systematic RAG evaluation metrics (Est. ~1 min)",
        packages=["ragas>=0.2.0", "huggingface-hub", "datasets", OPTIONAL_PROTOBUF_PIN],
        size_mb=150,
        check_import="ragas",
    ),
}


class SetupService:
    """
    Manages optional dependency installation.

    Features:
    - Detects which optional features are already installed
    - Installs features on-demand via async subprocess
    - Tracks installation status and errors
    - Persists setup completion state
    """

    # Package installation target directory - initialized in __init__
    PACKAGES_DIR: str = "/app/.packages"

    # Redis key for the cross-replica setup-complete flag. Best-effort: a
    # short socket timeout means a slow/unreachable Redis degrades to the
    # in-memory-only flag (today's behaviour) rather than stalling requests.
    _SETUP_COMPLETE_REDIS_KEY = "setup:complete"
    _REDIS_TIMEOUT_SECONDS = 0.2

    def __init__(self, redis_url: str | None = None):
        self._init_packages_dir()
        self._features = {k: Feature(**{**v.__dict__}) for k, v in OPTIONAL_FEATURES.items()}
        self._redis_url = redis_url
        self._redis_client_cache = None
        self._redis_unavailable = False
        self._setup_complete = self._read_setup_complete_from_redis() or False
        self._installation_lock = asyncio.Lock()

        # Ensure packages directory is in sys.path for dynamic imports
        self._setup_package_path()

        # Detect already installed features on init
        self._detect_installed_features()

    def _redis_client(self):
        """Best-effort sync Redis client, cached on the instance; None if
        unavailable/misconfigured or if a prior attempt already failed.

        Sync (not asyncio.Redis): this flag is read from a plain `def`
        method (`get_setup_status`) called from both sync and async call
        sites; a short socket timeout keeps a slow/unreachable Redis from
        stalling the request instead of just losing cross-replica sync."""
        if self._redis_client_cache is not None:
            return self._redis_client_cache
        if not self._redis_url or self._redis_unavailable:
            return None
        try:
            import redis as redis_sync

            self._redis_client_cache = redis_sync.from_url(
                self._redis_url,
                socket_timeout=self._REDIS_TIMEOUT_SECONDS,
                socket_connect_timeout=self._REDIS_TIMEOUT_SECONDS,
            )
            return self._redis_client_cache
        except Exception as e:
            logger.debug(f"SetupService: Redis client unavailable: {e}")
            self._redis_unavailable = True
            return None

    def _read_setup_complete_from_redis(self) -> bool | None:
        """Best-effort GET; None (not False) means "unknown, keep current"."""
        try:
            client = self._redis_client()
            if client is None:
                return None
            value = client.get(self._SETUP_COMPLETE_REDIS_KEY)
            return value is not None and value.decode() == "true"
        except Exception as e:
            logger.debug(f"SetupService: Redis read failed: {e}")
            self._redis_client_cache = None
            return None

    def _write_setup_complete_to_redis(self) -> None:
        """Best-effort SET; failures never block mark_setup_complete()."""
        try:
            client = self._redis_client()
            if client is None:
                return
            client.set(self._SETUP_COMPLETE_REDIS_KEY, "true")
        except Exception as e:
            logger.debug(f"SetupService: Redis write failed: {e}")
            self._redis_client_cache = None

    def _init_packages_dir(self) -> None:
        """Determine proper packages directory based on environment."""
        import os
        from pathlib import Path

        env_path = os.environ.get("PACKAGES_DIR")
        if env_path:
            self.PACKAGES_DIR = env_path
        elif os.path.exists("/app") and os.access("/app", os.W_OK):
            self.PACKAGES_DIR = "/app/.packages"
        else:
            # Fallback to project root .packages
            # src/api/services/setup_service.py -> src/api/services -> src/api -> src -> root
            project_root = Path(__file__).parent.parent.parent.parent
            self.PACKAGES_DIR = str(project_root / ".packages")

        # Ensure directory exists
        try:
            os.makedirs(self.PACKAGES_DIR, exist_ok=True)
            logger.info(f"Using packages directory: {self.PACKAGES_DIR}")
        except Exception as e:
            logger.error(f"Failed to create packages directory {self.PACKAGES_DIR}: {e}")

    def _setup_package_path(self) -> None:
        """Add custom packages directory to Python path."""
        packages_path = self.PACKAGES_DIR
        if packages_path not in sys.path:
            sys.path.insert(0, packages_path)
            logger.info(f"Added {packages_path} to sys.path")

    def _detect_installed_features(self) -> None:
        """Scan all features and update their installation status."""
        for feature_id, feature in self._features.items():
            try:
                module_present = util.find_spec(feature.check_import) is not None
            except (ImportError, ValueError):
                module_present = False
            if not module_present:
                continue

            mismatches = self._exact_version_mismatches(feature)
            if mismatches:
                feature.status = FeatureStatus.FAILED
                feature.error_message = FRESH_PACKAGES_VOLUME_REQUIRED
                logger.warning(
                    "Feature '%s' requires a fresh packages volume: %s",
                    feature_id,
                    ", ".join(mismatches),
                )
                continue

            if self._check_feature_installed(feature_id):
                feature.status = FeatureStatus.INSTALLED
                logger.info(f"Feature '{feature_id}' is already installed")

    @staticmethod
    def _exact_version_mismatches(feature: Feature) -> list[str]:
        """Return mismatches for exact pins without importing feature modules."""
        mismatches: list[str] = []
        for package_spec in feature.packages:
            if "==" not in package_spec:
                continue
            package_name, expected_version = package_spec.split("==", maxsplit=1)
            try:
                installed_version = metadata.version(package_name)
            except metadata.PackageNotFoundError:
                mismatches.append(f"{package_name}=missing (expected {expected_version})")
                continue
            if installed_version != expected_version:
                mismatches.append(
                    f"{package_name}={installed_version} (expected {expected_version})"
                )
        return mismatches

    def _check_feature_installed(self, feature_id: str) -> bool:
        """Check if a feature's packages are importable."""
        feature = self._features.get(feature_id)
        if not feature:
            return False

        try:
            if util.find_spec(feature.check_import) is None:
                return False
            mismatches = self._exact_version_mismatches(feature)
            if mismatches:
                logger.info("Feature '%s' version mismatch: %s", feature_id, ", ".join(mismatches))
                return False
            importlib.import_module(feature.check_import)
            return True
        except ImportError as e:
            logger.debug(f"Feature '{feature_id}' import check failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"Feature '{feature_id}' unexpected import error: {e}")
            return False

    def get_setup_status(self) -> dict[str, Any]:
        """Return current setup status for UI."""
        if not self._setup_complete:
            # Best-effort refresh: another replica may have completed setup
            # since this process's singleton was constructed.
            redis_value = self._read_setup_complete_from_redis()
            if redis_value:
                self._setup_complete = True
        features_status = []
        for feature in self._features.values():
            features_status.append(
                {
                    "id": feature.id,
                    "name": feature.name,
                    "description": feature.description,
                    "size_mb": feature.size_mb,
                    "status": feature.status.value,
                    "error_message": feature.error_message,
                    "packages": feature.packages,
                }
            )

        # Calculate totals
        total_features = len(self._features)
        installed_count = sum(
            1 for f in self._features.values() if f.status == FeatureStatus.INSTALLED
        )
        installing_count = sum(
            1 for f in self._features.values() if f.status == FeatureStatus.INSTALLING
        )

        return {
            "initialized": self._setup_complete or installed_count == total_features,
            "setup_complete": self._setup_complete,
            "features": features_status,
            "summary": {
                "total": total_features,
                "installed": installed_count,
                "installing": installing_count,
                "not_installed": total_features - installed_count - installing_count,
            },
        }

    async def install_feature(self, feature_id: str) -> dict[str, Any]:
        """
        Install a single feature's packages.

        Returns result dict with success status and any error message.
        """
        feature = self._features.get(feature_id)
        if not feature:
            return {"success": False, "error": f"Unknown feature: {feature_id}"}

        if feature.status == FeatureStatus.INSTALLED:
            return {"success": True, "message": "Already installed"}

        if (
            feature.status == FeatureStatus.FAILED
            and feature.error_message == FRESH_PACKAGES_VOLUME_REQUIRED
        ):
            return {"success": False, "error": FRESH_PACKAGES_VOLUME_REQUIRED}

        if feature.status == FeatureStatus.INSTALLING:
            return {"success": False, "error": "Installation already in progress"}

        async with self._installation_lock:
            feature.status = FeatureStatus.INSTALLING
            feature.error_message = None

            try:
                logger.info(f"Installing feature '{feature_id}': {feature.packages}")

                # Build pip command - install to custom packages directory
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "--no-cache-dir",
                    "--target",
                    self.PACKAGES_DIR,
                    *feature.pip_extra_args,
                    *feature.packages,
                ]

                # Run pip install
                # Set TMPDIR to a subdir of packages to ensure same-device for move operations
                import os

                env = os.environ.copy()
                tmp_dir = os.path.join(self.PACKAGES_DIR, ".tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                env["TMPDIR"] = tmp_dir

                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
                )

                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    # Verify installation
                    if self._check_feature_installed(feature_id):
                        feature.status = FeatureStatus.INSTALLED
                        logger.info(f"Feature '{feature_id}' installed successfully")
                        return {"success": True, "message": "Installed successfully"}
                    else:
                        feature.status = FeatureStatus.FAILED
                        feature.error_message = "Installation completed but import still fails"
                        return {"success": False, "error": feature.error_message}
                else:
                    feature.status = FeatureStatus.FAILED
                    feature.error_message = stderr.decode()[:500]  # Truncate long errors
                    logger.error(
                        f"Feature '{feature_id}' installation failed: {feature.error_message}"
                    )
                    return {"success": False, "error": feature.error_message}

            except Exception as e:
                feature.status = FeatureStatus.FAILED
                feature.error_message = str(e)
                logger.exception(f"Error installing feature '{feature_id}'")
                return {"success": False, "error": str(e)}

    async def install_features_batch(self, feature_ids: list[str]) -> dict[str, Any]:
        """Install multiple features sequentially."""
        results = {}
        for feature_id in feature_ids:
            results[feature_id] = await self.install_feature(feature_id)
        return results

    async def install_features_stream(self, feature_ids: list[str]):
        """
        Install features sequentially with streaming progress.

        Yields progress events as dicts:
        {
            "feature_id": str,
            "feature_name": str,
            "phase": "downloading" | "installing" | "verifying" | "complete" | "failed",
            "progress": int (0-100),
            "message": str,
            "current": int (1-indexed feature number),
            "total": int (total features to install)
        }
        """
        import os
        import re

        total = len(feature_ids)

        for idx, feature_id in enumerate(feature_ids, 1):
            feature = self._features.get(feature_id)
            if not feature:
                yield {
                    "feature_id": feature_id,
                    "feature_name": "Unknown",
                    "phase": "failed",
                    "progress": 0,
                    "message": f"Unknown feature: {feature_id}",
                    "current": idx,
                    "total": total,
                }
                continue

            if feature.status == FeatureStatus.INSTALLED:
                yield {
                    "feature_id": feature_id,
                    "feature_name": feature.name,
                    "phase": "complete",
                    "progress": 100,
                    "message": "Already installed",
                    "current": idx,
                    "total": total,
                }
                continue

            if (
                feature.status == FeatureStatus.FAILED
                and feature.error_message == FRESH_PACKAGES_VOLUME_REQUIRED
            ):
                yield {
                    "feature_id": feature_id,
                    "feature_name": feature.name,
                    "phase": "failed",
                    "progress": 0,
                    "message": FRESH_PACKAGES_VOLUME_REQUIRED,
                    "current": idx,
                    "total": total,
                }
                continue

            # Start installation
            feature.status = FeatureStatus.INSTALLING
            feature.error_message = None

            yield {
                "feature_id": feature_id,
                "feature_name": feature.name,
                "phase": "downloading",
                "progress": 0,
                "message": f"Starting installation of {feature.name}...",
                "current": idx,
                "total": total,
            }

            try:
                # Build pip command with progress output
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",  # Force upgrade/downgrade to match constraints
                    "--no-cache-dir",
                    "--progress-bar",
                    "on",
                    "--target",
                    self.PACKAGES_DIR,
                    *feature.pip_extra_args,
                    *feature.packages,
                ]

                # Prepare environment
                env = os.environ.copy()
                tmp_dir = os.path.join(self.PACKAGES_DIR, ".tmp")
                env["TMPDIR"] = tmp_dir
                os.makedirs(tmp_dir, exist_ok=True)

                # CLEANUP: Remove conflicting packages to prevent "ghost" versions in --target
                # This is crucial for fixing dependency hell (e.g. tokenizers 0.19 vs 0.22)
                import glob
                import shutil

                for pkg_spec in feature.packages:
                    # Extract package name (e.g. "tokenizers>=0.19" -> "tokenizers")
                    pkg_name = re.split(r"[<>=!]", pkg_spec)[0].strip()
                    logger.info(f"Cleaning existing artifacts for {pkg_name}...")

                    # Normalize (pip converts - to _)
                    name_variations = [pkg_name, pkg_name.replace("-", "_")]

                    for name in name_variations:
                        # 1. Remove dist-info (metadata)
                        # This removes 'ghost' versions like tokenizers-0.22.2.dist-info
                        for path in glob.glob(
                            os.path.join(self.PACKAGES_DIR, f"{name}-*.dist-info")
                        ):
                            try:
                                shutil.rmtree(path)
                                logger.debug(f"Removed ghost metadata: {path}")
                            except Exception as e:
                                logger.warning(f"Failed to remove {path}: {e}")

                        # 2. Remove package directory (optional, but safer)
                        # Skip large packages like torch to match original intent, OR clean all for robustness?
                        # For "fix forever", we clean verification-critical packages
                        if name in [
                            "tokenizers",
                            "transformers",
                            "huggingface_hub",
                            "sentence_transformers",
                        ]:
                            pkg_dir = os.path.join(self.PACKAGES_DIR, name)
                            if os.path.isdir(pkg_dir):
                                try:
                                    shutil.rmtree(pkg_dir)
                                    logger.debug(f"Removed package dir: {pkg_dir}")
                                except Exception as e:
                                    logger.warning(f"Failed to remove {pkg_dir}: {e}")

                # Build pip command with progress output

                os.makedirs(tmp_dir, exist_ok=True)
                env["TMPDIR"] = tmp_dir
                # Force pip to show progress
                env["PIP_PROGRESS_BAR"] = "on"

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
                    env=env,
                )

                logger.info(f"Started pip process for {feature.name}, cmd: {' '.join(cmd[:5])}...")

                current_phase = "downloading"
                last_progress = 0

                # Read output line by line
                line_count = 0
                async for line_bytes in process.stdout:
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    line_count += 1
                    # DEBUG: Log all pip output
                    logger.debug(f"PIP [{feature_id}]: {line[:150]}")

                    # Parse pip output for progress
                    message = line[:100]  # Truncate long lines

                    # Detect phase transitions and estimate progress
                    if "Collecting" in line or "Downloading" in line:
                        current_phase = "downloading"
                        # Increment progress during download (0-65%), cap at 65
                        # Approximation: each download line = ~0.5% progress (slower for large packages)
                        last_progress = min(65.0, last_progress + 0.5)
                    elif "Installing" in line or "Building" in line:
                        current_phase = "installing"
                        # Increment during installing phase (70-89)
                        if last_progress < 70:
                            last_progress = 70.0
                        else:
                            last_progress = min(89.0, last_progress + 0.5)
                    elif "Successfully installed" in line:
                        current_phase = "verifying"
                        last_progress = 90.0

                    yield {
                        "feature_id": feature_id,
                        "feature_name": feature.name,
                        "phase": current_phase,
                        "progress": int(last_progress),
                        "message": message,
                        "current": idx,
                        "total": total,
                    }

                await process.wait()

                if process.returncode == 0:
                    # Verify installation
                    yield {
                        "feature_id": feature_id,
                        "feature_name": feature.name,
                        "phase": "verifying",
                        "progress": 95,
                        "message": "Verifying installation...",
                        "current": idx,
                        "total": total,
                    }

                    if self._check_feature_installed(feature_id):
                        feature.status = FeatureStatus.INSTALLED
                        yield {
                            "feature_id": feature_id,
                            "feature_name": feature.name,
                            "phase": "complete",
                            "progress": 100,
                            "message": "Installed successfully",
                            "current": idx,
                            "total": total,
                        }
                    else:
                        # Try to get actual import error
                        try:
                            importlib.import_module(feature.check_import)
                            error_msg = "Unknown import error"
                        except Exception as import_error:
                            error_msg = str(import_error)[:100]

                        feature.status = FeatureStatus.FAILED
                        feature.error_message = f"Import verification failed: {error_msg}"
                        logger.error(f"Feature '{feature_id}' import failed: {error_msg}")
                        yield {
                            "feature_id": feature_id,
                            "feature_name": feature.name,
                            "phase": "failed",
                            "progress": 0,
                            "message": f"Import failed: {error_msg}",
                            "current": idx,
                            "total": total,
                        }
                else:
                    feature.status = FeatureStatus.FAILED
                    feature.error_message = f"pip exited with code {process.returncode}"
                    yield {
                        "feature_id": feature_id,
                        "feature_name": feature.name,
                        "phase": "failed",
                        "progress": 0,
                        "message": f"Installation failed (exit code {process.returncode})",
                        "current": idx,
                        "total": total,
                    }

            except Exception as e:
                feature.status = FeatureStatus.FAILED
                feature.error_message = str(e)
                logger.exception(f"Error installing feature '{feature_id}'")
                yield {
                    "feature_id": feature_id,
                    "feature_name": feature.name,
                    "phase": "failed",
                    "progress": 0,
                    "message": str(e)[:100],
                    "current": idx,
                    "total": total,
                }

    def mark_setup_complete(self) -> None:
        """Mark setup as complete (user skipped or finished)."""
        self._setup_complete = True
        self._write_setup_complete_to_redis()
        logger.info("Setup marked as complete")

    async def check_required_services(self) -> dict[str, Any]:
        """Check if required services (PostgreSQL, Neo4j, Milvus, Redis) are reachable."""
        results = {}

        # PostgreSQL check
        try:
            import asyncpg  # noqa: F401

            # Just check import works, actual connection test would need config
            results["postgresql"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["postgresql"] = {"status": "error", "message": "Missing asyncpg"}

        # Neo4j check
        try:
            import neo4j  # noqa: F401

            results["neo4j"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["neo4j"] = {"status": "error", "message": "Missing neo4j driver"}

        # Milvus check
        try:
            import pymilvus  # noqa: F401

            results["milvus"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["milvus"] = {"status": "error", "message": "Missing pymilvus"}

        # Redis check
        try:
            import redis  # noqa: F401

            results["redis"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["redis"] = {"status": "missing", "message": "redis not installed"}

        all_available = all(r["status"] == "available" for r in results.values())

        return {
            "all_available": all_available,
            "services": results,
        }


# Singleton instance
_setup_service: SetupService | None = None


def get_setup_service() -> SetupService:
    """Get or create the setup service singleton."""
    global _setup_service
    if _setup_service is None:
        from src.api.config import settings

        _setup_service = SetupService(redis_url=settings.redis_url)
    return _setup_service
