#!/bin/bash
watch -n 5 'docker exec amber2-neo4j-1 cypher-shell -u neo4j -p changeme "MATCH (c:Community) RETURN coalesce(c.status, \"pending\") AS status, count(*) AS cnt ORDER BY cnt DESC"'
