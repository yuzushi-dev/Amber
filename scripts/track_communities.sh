#!/bin/bash
# Usage: NEO4J_PASSWORD=xxx ./track_communities.sh
# or set NEO4J_PASSWORD in your environment
PASSWORD="${NEO4J_PASSWORD:?NEO4J_PASSWORD is not set}"
watch -n 5 "docker exec amber2-neo4j-1 cypher-shell -u neo4j -p \"$PASSWORD\" \"MATCH (c:Community) RETURN coalesce(c.status, 'pending') AS status, count(*) AS cnt ORDER BY cnt DESC\""
