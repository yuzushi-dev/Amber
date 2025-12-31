import logging
from typing import Any, Dict, List, Optional
from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from src.api.config import settings
from src.core.observability.tracer import trace_span

logger = logging.getLogger(__name__)

class Neo4jClient:
    """
    Async client for Neo4j Graph Database.
    Handles connection pooling and transaction management.
    """
    
    _driver: Optional[AsyncDriver] = None
    
    def __init__(self):
        self.uri = settings.db.neo4j_uri
        self.user = settings.db.neo4j_user
        self.password = settings.db.neo4j_password
        self._driver = None

    async def connect(self):
        """Establish connection to Neo4j."""
        if not self._driver:
            try:
                self._driver = AsyncGraphDatabase.driver(
                    self.uri, 
                    auth=(self.user, self.password)
                )
                # Verify connection
                await self._driver.verify_connectivity()
                logger.info("Connected to Neo4j at %s", self.uri)
            except Exception as e:
                logger.error("Failed to connect to Neo4j: %s", str(e))
                raise

    async def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    async def get_driver(self) -> AsyncDriver:
        """Get or create the driver instance."""
        if not self._driver:
            await self.connect()
        return self._driver

    @trace_span("Neo4j.execute_read")
    async def execute_read(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Execute a read-only transaction.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            List of records as dictionaries
        """
        driver = await self.get_driver()
        
        async with driver.session() as session:
            try:
                result = await session.execute_read(self._execute_tx, query, parameters)
                return result
            except Exception as e:
                logger.error("Read transaction failed: %s", str(e))
                raise

    @trace_span("Neo4j.execute_write")
    async def execute_write(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Execute a write transaction.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            List of records as dictionaries (if any)
        """
        driver = await self.get_driver()
        
        async with driver.session() as session:
            try:
                result = await session.execute_write(self._execute_tx, query, parameters)
                return result
            except Exception as e:
                logger.error("Write transaction failed: %s", str(e))
                raise

    async def _execute_tx(self, tx, query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Helper to run transaction and collect results."""
        if parameters is None:
            parameters = {}
            
        result = await tx.run(query, parameters)
        records = [record.data() async for record in result]
        return records

    async def verify_connectivity(self) -> bool:
        """Check if connected to Neo4j."""
        try:
            driver = await self.get_driver()
            await driver.verify_connectivity()
            return True
        except Exception:
            return False

# Global instance
neo4j_client = Neo4jClient()
