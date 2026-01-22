# Amber – Tenant & Role Model Proposal

This document formalizes the **tenant and role model** for Amber, based on the current implementation in the `feature/ollama-embeddings` branch and aligned with the intended evolution of the platform.

Amber today is **API-key–centric** and **multi-tenant**, with authorization split across:
- **Global scopes** (stored on API keys)
- **Per-tenant roles** (stored on the API key ↔ tenant association)

This proposal clarifies responsibilities, invariants, and future-proof extensions without requiring a rewrite.

---

## Core Concepts

### Platform
The Amber installation as a whole:
- Global configuration
- Tenant lifecycle
- Infrastructure maintenance
- Disaster recovery

### Tenant
A strict isolation boundary:
- Documents
- Chunks, embeddings, graphs
- Pipelines and runs
- Configuration
- API keys and users

All persisted and derived artifacts **must carry `tenant_id`**.

### Principal
An authenticated actor:
- Currently an **API key**
- Later extensible to users or service accounts

### Authorization Axes
Amber uses **two orthogonal authorization layers**:

1. **Scopes (global)**
   - Stored on `ApiKey.scopes`
   - Example: `super_admin`, `admin`, `active_user`
   - Loaded into request context by `AuthenticationMiddleware`

2. **Tenant Roles (local)**
   - Stored on `ApiKeyTenant.role`
   - Example: `admin`, `user`, `viewer`
   - Apply only within a specific tenant

---

## Roles Overview

### 1. Bootstrap Super Admin (Root Principal)

**What it is**
- The API key created at bootstrap (e.g. via `amber-dev-key-2024`)
- Permanently trusted root identity

**Invariants**
- Cannot be deleted, disabled, or demoted
- Cannot have `super_admin` revoked
- Exists even if all other admins are removed

**Scopes**
```
["admin", "root", "super_admin"]
```

**Capabilities**
- Full platform control
- Create / delete tenants
- Create other Super Admins
- Rotate bootstrap credentials
- Break-glass recovery
- Upload documents (explicit tenant context required)

> Recommendation: keep `root` as a semantic distinction even if unused today.

---

### 2. Super Admin (Platform Admin)

**Scope**
- Platform-wide

**Scopes**
```
["super_admin"]
```

**Capabilities**
- Manage tenants
- Assign tenant admins
- Create API keys across tenants
- Manage global configuration
- Debug and support tenant issues

**Important Design Choice**
Super Admins *can* see all data, but should ideally:
- Explicitly select a tenant context
- Have all cross-tenant access audited

---

### 3. Tenant Admin

**Scope**
- Single tenant

**Scopes**
```
["admin"]
```

**Tenant Role**
```
ApiKeyTenant.role = "admin"
```

**Capabilities**
- Manage tenant users / API keys
- Configure tenant-level settings
- Upload and delete tenant documents
- View all documents within the tenant
- View tenant audit data and ingestion status

**Limitations**
- No access to global settings
- No access to other tenants

---

### 4. Tenant User

**Scope**
- Single tenant

**Scopes**
```
["active_user"]
```

**Tenant Role**
```
ApiKeyTenant.role = "user"
```

**Capabilities**
- Upload documents to their tenant
- Query and read tenant documents
- Use retrieval and chat features

**Limitations**
- Cannot manage users or keys
- Cannot change tenant settings
- Optional: may only delete documents they uploaded

---

### 5. (Optional) Tenant Viewer

**Scope**
- Single tenant

**Scopes**
```
["read_only"]
```

**Tenant Role**
```
ApiKeyTenant.role = "viewer"
```

**Capabilities**
- Query and read tenant documents

**Limitations**
- No uploads
- No deletes
- No configuration access

Useful for stakeholders and auditors.

---

## Capability Matrix

| Capability              | Bootstrap SA |  Super Admin | Tenant Admin | Tenant User | Viewer |
| ----------------------- | -----------: | -----------: | -----------: | ----------: | -----: |
| Manage global settings  |            ✓ |            ✓ |            ✗ |           ✗ |      ✗ |
| Create / delete tenants |            ✓ |            ✓ |            ✗ |           ✗ |      ✗ |
| Assign Super Admin      |            ✓ | ✓ (not root) |            ✗ |           ✗ |      ✗ |
| Manage tenant users     |            ✓ |            ✓ |            ✓ |           ✗ |      ✗ |
| Upload documents        |            ✓ |            ✓ |            ✓ |           ✓ |      ✗ |
| Read tenant documents   |            ✓ |            ✓ |            ✓ |           ✓ |      ✓ |
| Delete tenant documents |            ✓ |            ✓ |            ✓ |          ✓* |      ✗ |
| Cross-tenant visibility |            ✓ |            ✓ |            ✗ |           ✗ |      ✗ |

\* recommended: users delete only their own uploads

---

## Mapping to Current Code

- **Scopes**
  - Stored in `ApiKey.scopes`
  - Injected into request context by `AuthenticationMiddleware`
- **Tenant Roles**
  - Stored in `ApiKeyTenant.role`
  - Default: `"user"`
- **Tenant Isolation**
  - Enforced via `app.current_tenant` (PostgreSQL RLS)
- **Super Admin Flag**
  - `app.is_super_admin = true` when `"super_admin"` is present

---

## Design Recommendations

### 1. Make Scopes Explicit and Minimal
Suggested canonical scopes:
```
root
super_admin
admin
active_user
read_only
```

Avoid free-form or overlapping meanings.

---

### 2. Separate Power From Visibility
Even if Super Admins *can* see all data:
- Require explicit tenant selection
- Log cross-tenant reads
- Optional support / impersonation mode with TTL

---

### 3. Always Propagate `tenant_id`
All artifacts must include:
- `tenant_id`
- (optional) `document_id`
- (optional) `owner_user_id`

This includes:
- Chunks
- Embeddings
- Graph nodes
- Caches
- Background jobs

---

### 4. Future-Proofing: Users and Workspaces

You can later extend without breaking changes:

```
Platform
 └── Tenant
      └── Workspace (optional)
           └── Resources
```

API keys and users can both map cleanly onto this hierarchy.

---

## Summary

This role model:
- Matches the current Amber implementation
- Clearly separates platform vs tenant authority
- Preserves strict tenant isolation
- Allows safe evolution toward enterprise features
- Prevents accidental privilege escalation

It is intentionally minimal, explicit, and enforceable at the database, API, and service layers.

---

## Chat & Feedback Privacy

To balance user trust with administrative oversight, we enforce strict privacy boundaries for conversational data.

### 1. Chat Content Privacy
**Invariant:** **No Admin (Tenant or Super) can read the message content of a User's chat.**
- **User:** Users can only see their own chat history.
- **Tenant Admin:** Can see *metadata* (token count, cost, timestamps, user ID) but **NOT** the query text or AI response.
- **Super Admin:** Can see *metadata* for all tenants but **NOT** the query text or AI response.

*Rationale: Prevents sensitive employee queries (e.g., HR, whistleblowing) from being monitored by local admins.*

### 2. Feedback Visibility
When a user provides feedback (👍/👎, comments, corrections), this specific data point becomes visible for quality assurance.
- **Tenant Admin:** Sees feedback **only** for users within their tenant at `/admin/metrics/feedback`.
- **Super Admin:** Sees feedback for **all** tenants.

---

## Metrics & Configuration Matrix

Access control for specific administrative modules:

| Module             | URL Path                         | Tenant Admin Visibility                                   | Super Admin Visibility                               | Data Source / storage                                                                  |
| ------------------ | -------------------------------- | --------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Token Metrics**  | `/admin/metrics/tokens`          | **Tenant Only**<br>(Own usage & cost)                     | **Global**<br>(Aggregated or specific tenant)        | `UsageLog` (filtered by `tenant_id`)                                                   |
| **Feedback**       | `/admin/metrics/feedback`        | **Tenant Only**<br>(Corrects/Comments)                    | **Global**<br>(All feedback)                         | `Feedback` (filtered by `tenant_id`)                                                   |
| **System Health**  | `/admin/metrics/system`          | **None**<br>(Infrastructure is managed by Platform)       | **Full Access**<br>(CPU, RAM, Disk, Queue latencies) | Prometheus / Celery / System Monitoring                                                |
| **RAG Evaluation** | `/admin/metrics/ragas`           | **None**<br>(High-level model eval is a platform concern) | **Full Access**<br>(Deep model performance quality)  | `BenchmarkRun` / `Ragas` Results                                                       |
| **Rules**          | `/admin/settings/rules`          | **Tenant Specific**<br>(Manage rules for own agent)       | **Global Defaults**<br>(Set baseline rules for all)  | **Proposed:** Add `tenant_id` to `GlobalRule`.<br>Null `tenant_id` = System User Rule. |
| **Data Retention** | `/admin/settings/data-retention` | **Tenant Specific**<br>(Configure own retention policy)   | **Global Limits**<br>(Enforce max caps)              | `Tenant.config` JSON                                                                   |
