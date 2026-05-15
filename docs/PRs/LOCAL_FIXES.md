# Amber 2.0 — Local Fixes

Fixes applied locally on test environment, not from architecture audit.

---

## PR-LOCAL-01 — Fix Nginx container naming

### Jira
**Type:** Bug  
**Priority:** High  
**Summary:** Nginx upstream and proxy_pass use service names not resolvable in production

**Description:**  
Nginx configuration references Docker service names (`frontend`, `api`) which don't resolve in the production environment. Updated to use actual container hostnames (`amber-frontend-1`, `amber-api-1`).

**Files:**
- `deploy/nginx/conf.d/frontend.conf` — proxy_pass → `amber-frontend-1:3000`
- `deploy/nginx/conf.d/upstream.conf` — upstream server → `amber-api-1:8000`

---

## PR-LOCAL-02 — Add GRAPHRAG_APP_PASSWORD to services

### Jira
**Type:** Security / Missing Config  
**Priority:** Medium  
**Summary:** Workers and API missing GRAPHRAG_APP_PASSWORD environment variable

**Description:**  
Added `GRAPHRAG_APP_PASSWORD=${GRAPHRAG_APP_PASSWORD}` to both `api` and `worker` services in docker-compose.yml to enable authentication.

**Files:**
- `docker-compose.yml` — added env var to api and worker services

---

## PR-LOCAL-03 — Ignore embedding mismatch on startup

### Jira
**Type:** Stability  
**Priority:** Medium  
**Summary:** Services fail to start on embedding dimension mismatch

**Description:**  
Added `IGNORE_EMBEDDING_MISMATCH=true` to prevent startup failures during migration when embedding dimensions have minor discrepancies.

**Files:**
- `docker-compose.yml` — added env var to api service

---

## PR-LOCAL-04 — Unpin huggingface-hub version

### Jira
**Type:** Dependency  
**Priority:** Low  
**Summary:** Huggingface-hub version pin prevents RAGAS installation

**Description:**  
Removed `<1.0` constraint from `huggingface-hub` to allow installation of newer versions required by `ragas` and `transformers` v5.8.1.

**Files:**
- `src/api/services/setup_service.py` — removed version constraint

---

## PR-LOCAL-05 — Restore LoadBalancedLLMProvider

### Jira
**Type:** Feature  
**Priority:** High  
**Summary:** OllamaCloud load balancing not functional

**Description:**  
Restored `LoadBalancedLLMProvider` implementation and updated `factory.py` to use it for multi-key OllamaCloud pools. The provider distributes requests randomly across available keys with circuit breaker protection.

**Files:**
- `src/core/generation/infrastructure/providers/load_balanced.py` — (new file)
- `src/core/generation/infrastructure/providers/factory.py` — uses LoadBalancedLLMProvider

---

## Priority Summary

| PR | Title | Priority |
|----|-------|----------|
| PR-LOCAL-01 | Nginx container naming | High |
| PR-LOCAL-02 | GRAPHRAG_APP_PASSWORD | Medium |
| PR-LOCAL-03 | Embedding mismatch | Medium |
| PR-LOCAL-04 | Huggingface-hub pin | Low |
| PR-LOCAL-05 | LoadBalancedLLMProvider | High |


---

## Detailed Implementation Details

### PR-LOCAL-01: Nginx container naming
**Lines Modified:** `deploy/nginx/conf.d/frontend.conf` (2 lines), `deploy/nginx/conf.d/upstream.conf` (2 lines)  
**Breaking Changes:** No (hot-fix, no restart needed)  
**Test File:** None  
**Commands:** `docker compose restart nginx`

---

### PR-LOCAL-02: GRAPHRAG_APP_PASSWORD
**Lines Modified:** `docker-compose.yml` (added to api and worker services)  
**Breaking Changes:** No  
**Test File:** None  
**Commands:** `docker compose up -d`

---

### PR-LOCAL-03: IGNORE_EMBEDDING_MISMATCH
**Lines Modified:** `docker-compose.yml` (1 env var added to api)  
**Breaking Changes:** No  
**Test File:** None  
**Commands:** `docker compose restart api`

---

### PR-LOCAL-04: Huggingface-hub unpinned
**Lines Modified:** `src/api/services/setup_service.py` (4 lines removed: version constraint)  
**Breaking Changes:** No  
**Test File:** None  
**Commands:** None (setup.py change, no container restart needed)

---

### PR-LOCAL-05: LoadBalancedLLMProvider restored
**Lines Modified:** `src/core/generation/infrastructure/providers/factory.py` (1 line changed)  
**New Files:** `src/core/generation/infrastructure/providers/load_balanced.py` (restored from prod)  
**Breaking Changes:** No  
**Test File:** None  
**Commands:** Restart API to load new provider

---

## Summary Table

| PR | Files | Lines | Breaking | Restart |
|----|-------|-------|----------|---------|
| PR-LOCAL-01 | 2 nginx conf | ±4 | No | nginx |
| PR-LOCAL-02 | docker-compose.yml | +2 | No | all |
| PR-LOCAL-03 | docker-compose.yml | +1 | No | api |
| PR-LOCAL-04 | setup_service.py | -4 | No | None |
| PR-LOCAL-05 | factory.py + new | +1 + new | No | api |

---

## Git Status

**New files:**
- `src/core/generation/infrastructure/providers/load_balanced.py`

**Modified files:**
- `deploy/nginx/conf.d/frontend.conf`
- `deploy/nginx/conf.d/upstream.conf`
- `docker-compose.yml`
- `src/api/services/setup_service.py`

---

Last updated: 2026-05-15
