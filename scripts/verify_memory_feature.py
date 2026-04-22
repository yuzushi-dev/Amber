import asyncio
import logging
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.api.config import settings
from src.core.memory.extractor import memory_extractor
from src.core.memory.manager import memory_manager
from src.core.providers.factory import init_providers

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFICATION")

TENANT_ID = "verification_tenant"
USER_ID = "verification_user"

# Initialize Providers
try:
    init_providers(
        openai_api_key=settings.openai_api_key,
        anthropic_api_key=settings.anthropic_api_key
    )
    logger.info("Providers initialized")
except Exception as e:
    logger.error(f"Failed to init providers: {e}")
    sys.exit(1)

async def test_pii_redaction():
    logger.info("--- TEST 1: PII Redaction ---")

    # Input with PII
    text = "My name is John Doe, my email is john@example.com and my SSN is 123-45-6789. I like Python."

    logger.info(f"Input: {text}")

    # Run extraction (should scrub PII before sending to LLM, and prompt should ignore it)
    facts = await memory_extractor.extract_and_save_facts(TENANT_ID, USER_ID, text)

    logger.info(f"Extracted Facts: {facts}")

    # Verify no PII in facts
    for fact in facts:
        if "John" in fact or "Doe" in fact or "john@example.com" in fact or "123-45-6789" in fact:
            logger.error("❌ PII LEAKED into facts!")
            return False

    if "Python" in str(facts) or "user likes Python" in str(facts).lower():
         logger.info("✅ Valid fact extracted (User likes Python)")
    else:
         logger.warning("⚠️ 'User likes Python' fact might have been missed (depends on LLM)")

    logger.info("✅ PII Redaction Passed (No PII found in output)")
    return True

async def test_fact_persistence():
    logger.info("--- TEST 2: Fact Persistence ---")

    # manually add a fact to ensure DB works
    await memory_manager.add_user_fact(TENANT_ID, USER_ID, "User is testing memory features", importance=1.0)

    # Retrieve
    stored_facts = await memory_manager.get_user_facts(TENANT_ID, USER_ID)
    logger.info(f"Stored Facts from DB: {[f.content for f in stored_facts]}")

    found = any("User is testing memory features" in f.content for f in stored_facts)
    if found:
        logger.info("✅ Fact persisted and retrieved successfully")
        return True
    else:
        logger.error("❌ Fact not found in DB")
        return False

async def test_summarization():
    logger.info("--- TEST 3: Summarization ---")

    history = [
        {"role": "user", "content": "How do I configure VS Code for Python?"},
        {"role": "assistant", "content": "You need to install the Python extension and select your interpreter."},
        {"role": "user", "content": "That worked, thanks! I prefer using black for formatting."},
        {"role": "assistant", "content": "Great! You can configure black in settings.json."}
    ]

    summary = await memory_extractor.summarize_and_save_conversation(
        TENANT_ID, USER_ID, "conv_123", history
    )

    logger.info(f"Generated Summary: {summary}")

    if summary and len(summary) > 10:
        logger.info("✅ Summary generated")

        # Verify persistence
        recent = await memory_manager.get_recent_summaries(TENANT_ID, USER_ID)
        if recent and recent[0].id == "conv_123":
            logger.info("✅ Summary persisted in DB")
            return True
        else:
            logger.error("❌ Summary not found in DB")
            return False
    else:
        logger.error("❌ Failed to generate summary")
        return False

async def cleanup():
    logger.info("--- Cleanup ---")
    # Delete facts
    facts = await memory_manager.get_user_facts(TENANT_ID, USER_ID)
    for f in facts:
        await memory_manager.delete_user_fact(TENANT_ID, f.id)

    # Delete summary
    await memory_manager.delete_conversation_summary(TENANT_ID, "conv_123")
    logger.info("Cleanup complete")

async def main():
    try:
        if await test_pii_redaction() and await test_fact_persistence() and await test_summarization():
            logger.info("\n🎉 ALL TESTS PASSED")
        else:
            logger.error("\n💥 SOME TESTS FAILED")
    finally:
        await cleanup()

if __name__ == "__main__":
    asyncio.run(main())
