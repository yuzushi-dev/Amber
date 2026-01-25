
import asyncio
import uuid
import sys
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv()

from src.api.config import settings
from src.core.generation.domain.memory_models import ConversationSummary
from src.core.admin_ops.domain.feedback import Feedback

async def verify_deletion():
    print("="*50)
    print("VERIFYING CONVERSATION DELETION CASCADE")
    print("="*50)

    # DB Connection
    db_url = settings.db.database_url
    if "postgres:5432" in db_url:
        db_url = db_url.replace("postgres:5432", "localhost:5433")
    
    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    conv_id = str(uuid.uuid4())
    feedback_id = str(uuid.uuid4())

    async with async_session() as session:
        print(f"1. Creating Conversation {conv_id}")
        conv = ConversationSummary(
            id=conv_id,
            tenant_id="default",
            user_id="user_1",
            title="Test Deletion",
            summary="This is a test summary."
        )
        session.add(conv)
        
        print(f"2. Creating Feedback {feedback_id} linked to {conv_id}")
        fb = Feedback(
            id=feedback_id,
            request_id=conv_id,
            tenant_id="default",
            score=1.0,
            comment="Great answer"
        )
        session.add(fb)
        await session.commit()

        # Verify creation
        assert await session.get(ConversationSummary, conv_id) is not None
        assert await session.get(Feedback, feedback_id) is not None

        print("3. Deleting Conversation...")
        await session.delete(conv)
        await session.commit()

        print("4. Checking Feedback existence...")
        fb_check = await session.get(Feedback, feedback_id)
        
        if fb_check:
            print("❌ FAILURE: Feedback persisted! It is now an orphan.")
        else:
            print("✅ SUCCESS: Feedback was deleted.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify_deletion())
