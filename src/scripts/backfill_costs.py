import asyncio
import json
import logging
import os
import sys
from collections import Counter

# Add src to path
sys.path.append(os.getcwd())

import redis.asyncio as redis

from src.api.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill")

# Pricing for o1 (Per Token)
# Input: $15 / 1M = $0.015 / 1k = 0.000015
# Output: $60 / 1M = $0.06 / 1k = 0.00006
O1_INPUT_COST_PER_TOKEN = 0.015 / 1000
O1_OUTPUT_COST_PER_TOKEN = 0.06 / 1000


async def backfill():
    url = settings.db.redis_url
    logger.info(f"Connecting to Redis at {url}")
    try:
        client = redis.from_url(url, decode_responses=True)
        await client.ping()
        logger.info("Connected successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return

    cursor = "0"
    updated_count = 0
    scanned_count = 0
    model_counts = Counter()

    logger.info("Starting scan...")

    try:
        while True:
            cursor, keys = await client.scan(cursor, match="metrics:query:*", count=100)

            for key in keys:
                scanned_count += 1
                try:
                    data_str = await client.get(key)
                    if not data_str:
                        continue

                    data = json.loads(data_str)
                    model = data.get("model", "") or ""
                    model_counts[model] += 1

                    # Debug logic
                    if "o1" in model.lower():
                        logger.info(
                            f"FOUND O1-like key: {key}, Model: {model}, Cost: {data.get('cost_estimate')}"
                        )

                    if model == "":
                        # Check if this looks like the 'o1' bug (High tokens, low cost)
                        # e.g. > 500 tokens but cost is < 0.001 (implies < $2/1M pricing)
                        cost = float(data.get("cost_estimate", 0))
                        tokens = int(data.get("tokens_used", 0))

                        if tokens > 500 and cost < 0.002:
                            logger.info(
                                f"SUSPICIOUS EMPTY MODEL: Key={key}, Tokens={tokens}, Cost={cost}. Likely mislabeled."
                            )
                            if key == "metrics:query:qry_1a1300ab15de4cdd":
                                logger.info(f"FULL DATA: {json.dumps(data, indent=2)}")

                    # Check if it's an o1 query
                    # STRICTLY o1, ignoring mini/preview if they have diff pricing,
                    # but for now o1 is the main concern.
                    if "o1" in model.lower() and "mini" not in model.lower():
                        # Calculate correct cost
                        input_tokens = int(data.get("input_tokens", 0))
                        output_tokens = int(data.get("output_tokens", 0))

                        correct_cost = (input_tokens * O1_INPUT_COST_PER_TOKEN) + (
                            output_tokens * O1_OUTPUT_COST_PER_TOKEN
                        )
                        current_cost = float(data.get("cost_estimate", 0.0))

                        # Check discrepancy (use 0.001 as threshold to avoid float noise)
                        if abs(correct_cost - current_cost) > 0.001:
                            logger.info(
                                f"Fixing {key} | Model: {model} | Tokens: {input_tokens}/{output_tokens} | Cost: {current_cost:.5f} -> {correct_cost:.5f}"
                            )

                            data["cost_estimate"] = correct_cost

                            # Preserve TTL
                            ttl = await client.ttl(key)
                            if ttl < 0:
                                ttl = 30 * 86400  # Default retention if no TTL

                            await client.setex(key, ttl, json.dumps(data))
                            updated_count += 1

                except Exception as e:
                    logger.error(f"Error processing key {key}: {e}")

            if cursor == 0:
                break

    except Exception as e:
        logger.error(f"Scan failed: {e}")
    finally:
        await client.close()

    logger.info(
        f"Backfill complete. Scanned: {scanned_count} keys, Updated: {updated_count} records"
    )
    logger.info(f"Model Distribution: {dict(model_counts)}")


if __name__ == "__main__":
    asyncio.run(backfill())
