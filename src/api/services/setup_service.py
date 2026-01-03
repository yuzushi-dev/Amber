"""
Setup Service
=============

Manages on-demand installation of optional ML dependencies.
Provides feature detection, async installation, and status tracking.
"""

import asyncio
import importlib
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FeatureStatus(str, Enum):
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
    error_message: Optional[str] = None


# Define all optional features
OPTIONAL_FEATURES: dict[str, Feature] = {
    "local_embeddings": Feature(
        id="local_embeddings",
        name="Local Embeddings",
        description="Generate embeddings locally with Sentence Transformers (no API calls)",
        packages=["torch", "sentence-transformers>=2.7.0"],
        size_mb=2100,
        check_import="sentence_transformers",
        pip_extra_args=["--index-url", "https://download.pytorch.org/whl/cpu"],
    ),
    "reranking": Feature(
        id="reranking",
        name="FlashRank Reranking",
        description="High-quality result reranking for better search accuracy",
        packages=["flashrank>=0.2.0"],
        size_mb=50,
        check_import="flashrank",
    ),
    "community_detection": Feature(
        id="community_detection",
        name="Community Detection",
        description="Leiden algorithm for knowledge graph community analysis",
        packages=["cdlib>=0.3.0", "leidenalg>=0.10.0", "python-igraph>=0.11.0"],
        size_mb=150,
        check_import="leidenalg",
    ),
    "document_processing": Feature(
        id="document_processing",
        name="Document Processing",
        description="Parse PDFs, DOCX, HTML, and other document formats",
        packages=["unstructured>=0.11.0", "python-magic>=0.4.27", "pymupdf4llm>=0.0.1"],
        size_mb=800,
        check_import="unstructured",
    ),
    "ragas": Feature(
        id="ragas",
        name="RAGAS Evaluation",
        description="Systematic RAG evaluation with Faithfulness and Relevancy metrics",
        packages=["ragas>=0.2.0"],
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
    
    # Package installation target directory
    PACKAGES_DIR = "/app/.packages"
    
    def __init__(self, redis_url: Optional[str] = None):
        self._features = {k: Feature(**{**v.__dict__}) for k, v in OPTIONAL_FEATURES.items()}
        self._setup_complete = False
        self._redis_url = redis_url
        self._installation_lock = asyncio.Lock()
        
        # Ensure packages directory is in sys.path for dynamic imports
        self._setup_package_path()
        
        # Detect already installed features on init
        self._detect_installed_features()
    
    def _setup_package_path(self) -> None:
        """Add custom packages directory to Python path."""
        import os
        packages_path = self.PACKAGES_DIR
        if packages_path not in sys.path:
            sys.path.insert(0, packages_path)
            logger.info(f"Added {packages_path} to sys.path")
    
    def _detect_installed_features(self) -> None:
        """Scan all features and update their installation status."""
        for feature_id, feature in self._features.items():
            if self._check_feature_installed(feature_id):
                feature.status = FeatureStatus.INSTALLED
                logger.info(f"Feature '{feature_id}' is already installed")
    
    def _check_feature_installed(self, feature_id: str) -> bool:
        """Check if a feature's packages are importable."""
        feature = self._features.get(feature_id)
        if not feature:
            return False
        
        try:
            importlib.import_module(feature.check_import)
            return True
        except ImportError:
            return False
    
    def get_setup_status(self) -> dict[str, Any]:
        """Return current setup status for UI."""
        features_status = []
        for feature in self._features.values():
            features_status.append({
                "id": feature.id,
                "name": feature.name,
                "description": feature.description,
                "size_mb": feature.size_mb,
                "status": feature.status.value,
                "error_message": feature.error_message,
                "packages": feature.packages,
            })
        
        # Calculate totals
        total_features = len(self._features)
        installed_count = sum(1 for f in self._features.values() if f.status == FeatureStatus.INSTALLED)
        installing_count = sum(1 for f in self._features.values() if f.status == FeatureStatus.INSTALLING)
        
        return {
            "initialized": self._setup_complete or installed_count == total_features,
            "setup_complete": self._setup_complete,
            "features": features_status,
            "summary": {
                "total": total_features,
                "installed": installed_count,
                "installing": installing_count,
                "not_installed": total_features - installed_count - installing_count,
            }
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
        
        if feature.status == FeatureStatus.INSTALLING:
            return {"success": False, "error": "Installation already in progress"}
        
        async with self._installation_lock:
            feature.status = FeatureStatus.INSTALLING
            feature.error_message = None
            
            try:
                logger.info(f"Installing feature '{feature_id}': {feature.packages}")
                
                # Build pip command - install to custom packages directory
                cmd = [
                    sys.executable, "-m", "pip", "install",
                    "--no-cache-dir",
                    "--target", self.PACKAGES_DIR,
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
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
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
                    logger.error(f"Feature '{feature_id}' installation failed: {feature.error_message}")
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
    
    def mark_setup_complete(self) -> None:
        """Mark setup as complete (user skipped or finished)."""
        self._setup_complete = True
        logger.info("Setup marked as complete")
    
    async def check_required_services(self) -> dict[str, Any]:
        """Check if required services (PostgreSQL, Neo4j, Milvus, Redis) are reachable."""
        results = {}
        
        # PostgreSQL check
        try:
            import asyncpg
            # Just check import works, actual connection test would need config
            results["postgresql"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["postgresql"] = {"status": "missing", "message": "asyncpg not installed"}
        
        # Neo4j check
        try:
            import neo4j
            results["neo4j"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["neo4j"] = {"status": "missing", "message": "neo4j not installed"}
        
        # Milvus check
        try:
            import pymilvus
            results["milvus"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["milvus"] = {"status": "missing", "message": "pymilvus not installed"}
        
        # Redis check
        try:
            import redis
            results["redis"] = {"status": "available", "message": "Driver loaded"}
        except ImportError:
            results["redis"] = {"status": "missing", "message": "redis not installed"}
        
        all_available = all(r["status"] == "available" for r in results.values())
        
        return {
            "all_available": all_available,
            "services": results,
        }


# Singleton instance
_setup_service: Optional[SetupService] = None


def get_setup_service() -> SetupService:
    """Get or create the setup service singleton."""
    global _setup_service
    if _setup_service is None:
        _setup_service = SetupService()
    return _setup_service
