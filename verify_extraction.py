
import asyncio
import os
import sys
import logging

# Setup mocking for MinIO and DB to isolate extraction logic
sys.path.append(os.getcwd())

from src.core.extraction.fallback import FallbackManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_extraction():
    file_path = "dev references/test files/CarbonioUserGuide.pdf"
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    logger.info(f"Reading file: {file_path}")
    with open(file_path, "rb") as f:
        content = f.read()

    logger.info(f"File size: {len(content)} bytes")
    
    try:
        logger.info("Starting extraction...")
        # We call the same method used in IngestionService
        result = await FallbackManager.extract_with_fallback(
            file_content=content,
            mime_type="application/pdf",
            filename="CarbonioUserGuide.pdf"
        )
        
        logger.info("Extraction Completed!")
        logger.info(f"Extractor used: {result.extractor_used}")
        logger.info(f"Extracted content length: {len(result.content)} characters")
        logger.info(f"Metadata: {result.metadata}")
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_extraction())
