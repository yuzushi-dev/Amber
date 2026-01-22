# Tenant Role Model Implementation

## Overview

This document details the implementation of the **Tenant Role Model** in Amber. This model enforces strict role-based access control (RBAC) and data isolation across the application, introducing a dual-tier administration system: **Super Admin** and **Tenant Admin**.

The goal is to ensure that while a Super Admin has global oversight, Tenant Admins are empowered to manage their specific environment without accessing sensitive data from other tenants or modifying critical system-level configurations.

## Roles & Responsibilities

| Role             | Description                         | Scope                | Key Capabilities                                                                                                                                                                                                   |
| :--------------- | :---------------------------------- | :------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Super Admin**  | Platform-wide administrator         | Global (All Tenants) | • Create/Delete Tenants<br>• System Maintenance (Cache, Stats)<br>• Manage Global Providers & Embeddings<br>• View all API Keys & Chats<br>• Link/Unlink Keys to Tenants manually                                  |
| **Tenant Admin** | Administrator for a specific tenant | Single Tenant        | • Manage Tenant Settings (Update only)<br>• Create/Manage Users & Admins (via Keys)<br>• Manage standard RAG features (Rules, Prompts)<br>• **cannot** create new tenants<br>• **cannot** view other tenants' data |
| **User**         | Standard consumer                   | Single Tenant        | • Chat / Query<br>• Give Feedback                                                                                                                                                                                  |

## Technical Implementation

### 1. Authentication Middleware (`src/api/middleware/auth.py`)

The authentication layer has been refactored to resolve and inject role-specific metadata into the request lifecycle.

- **Tenant Role Injection**: When an API key is verified, the middleware checks the `api_key_tenants` table to identify the specific role (`admin` or `user`) linked to the tenant accessing the resource.
- **Super Admin Flag**: The `scopes` of the API Key are checked for `"super_admin"`.
- **Request State**: The following attributes are available on `request.state`:
    - `tenant_id`: The ID of the acting tenant.
    - `tenant_role`: The role within that tenant (`"admin"` or `"user"`).
    - `is_super_admin`: Boolean flag.

### 2. Dependency Injection (`src/api/deps.py`)

We introduced granular dependency functions to declarative enforce security on routes:

#### `verify_tenant_admin`
Requires the user to be an **Admin** within the current tenant OR a **Super Admin**.
```python
async def verify_tenant_admin(request: Request):
    if request.state.is_super_admin:
        return
    if request.state.tenant_role != "admin":
        raise HTTPException(403, "Tenant Admin privileges required")
```

#### `verify_super_admin`
Requires the user to explicitly be a **Super Admin**. Used for destructive or system-wide actions.
```python
async def verify_super_admin(request: Request):
    if not request.state.is_super_admin:
        raise HTTPException(403, "Super Admin privileges required")
```

## Feature Specifications

### A. Privacy & Data Isolation (Chat History)

A strict invariant is enforced: **"No Admin can read the message content of a User's chat unless it is their own."**

- **Implementation**: `src/api/routes/admin/chat_history.py`
- **Logic**:
    - When listing or viewing chat details, the system checks if `request.user.id == chat.user_id`.
    - If `False` (viewing another user's chat), the content is proactively redacted.
- **Redaction**:
    - Query Text: Replaced with `[REDACTED - ADMIN VIEW]`
    - Response Text: Replaced with `[REDACTED - ADMIN VIEW]`

### B. API Key Management (`src/api/routes/admin/keys.py`)

API Key management logic now adapts based on the caller's role:

- **Listing Keys**:
    - **Super Admin**: Views all keys in the system.
    - **Tenant Admin**: Views *only* keys associated with their tenant ID.
- **Creating Keys**:
    - **Tenant Admin**: New keys are **automatically linked** to the creator's tenant. They can only create keys for their own tenant.
    - **Super Admin**: Can properly specify a specific `tenant_id` to link the new key to.
- **Modifying Keys**:
    - Tenants Admins can only update/revoke keys they own.

### C. Tenant Management (`src/api/routes/admin/tenants.py`)

- **Create/Delete**: Strictly restricted to **Super Admin**. This prevents unauthorized proliferation of tenants or accidental deletion of infrastructure.
- **Read/Update**:
    - **Super Admin**: Can access/modify any tenant.
    - **Tenant Admin**: Can only access `GET /tenants/{their_id}` and `PATCH /tenants/{their_id}`. Attempts to access others result in 403 Forbidden.

### D. System-Level Operations

Crucial system endpoints are locked down to **Super Admin** only:

- **Embeddings**: `src/api/routes/admin/embeddings.py` (Migrations, Compatibility checks)
- **Providers**: `src/api/routes/admin/providers.py` (Adding/Removing global LLM providers)
- **Maintenance**: `src/api/routes/admin/maintenance.py` (Cache clearing, Database statistics)



## Future Considerations

- **Scope Validation**: Future hardening could include strict validation of *scopes* assigned by Tenant Admins (e.g., ensuring a Tenant Admin cannot grant `super_admin` scope to a new key).
- **Audit Logging**: Enhanced logging for "Redacted View" events to track administrative access patterns.
