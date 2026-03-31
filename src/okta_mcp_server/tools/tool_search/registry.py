# The Okta software accompanied by this notice is provided pursuant to the following terms:
# Copyright © 2025-Present, Okta, Inc.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0.
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and limitations under the License.

"""
Tool registry containing metadata for all Okta MCP Server tools.

This catalog is the single source of truth for tool discovery via search_tools.
When adding new tools to the server, register them here as well.
"""

TOOL_CATALOG = [
    # ─── Users ───────────────────────────────────────────────────────────
    {
        "name": "list_users",
        "category": "users",
        "description": (
            "List all users from the Okta organization with pagination support. "
            "Supports search, filter, and query parameters on user profile attributes. "
            "By default only returns users whose status is not DEPROVISIONED."
        ),
        "parameters": {
            "search": "str – Search string for specific users (e.g., profile.organization eq \"Okta\")",
            "filter": "str – Filter by Okta profile attributes",
            "q": "str – Query string to search by Okta profile attributes",
            "fetch_all": "bool – Auto-fetch all pages (default: False)",
            "after": "str – Pagination cursor for next page",
            "limit": "int – Results per page (min 20, max 100)",
        },
        "tags": ["list", "search", "read", "users", "pagination", "profile"],
    },
    {
        "name": "get_user",
        "category": "users",
        "description": "Get a single user by ID from the Okta organization.",
        "parameters": {
            "user_id": "str (required) – The ID of the user to retrieve",
        },
        "tags": ["get", "read", "users", "lookup"],
    },
    {
        "name": "get_user_profile_attributes",
        "category": "users",
        "description": (
            "List all user profile attributes supported by your Okta org. "
            "Useful to check whether a profile attribute name is valid before searching."
        ),
        "parameters": {},
        "tags": ["get", "read", "users", "profile", "attributes", "schema"],
    },
    {
        "name": "create_user",
        "category": "users",
        "description": "Create a new user in the Okta organization with the provided profile.",
        "parameters": {
            "profile": "dict (required) – User profile (email, login, firstName, lastName, etc.)",
        },
        "tags": ["create", "write", "users"],
    },
    {
        "name": "update_user",
        "category": "users",
        "description": "Update an existing user in the Okta organization with the provided profile.",
        "parameters": {
            "user_id": "str (required) – The ID of the user to update",
            "profile": "dict (required) – Updated profile fields",
        },
        "tags": ["update", "write", "users"],
    },
    {
        "name": "deactivate_user",
        "category": "users",
        "description": (
            "Deactivate a user from the Okta organization. "
            "Requires confirmation. Deactivation is a prerequisite for deletion."
        ),
        "parameters": {
            "user_id": "str (required) – The ID of the user to deactivate",
        },
        "tags": ["deactivate", "write", "users", "lifecycle"],
    },
    {
        "name": "delete_deactivated_user",
        "category": "users",
        "description": (
            "Permanently delete a user who has already been deactivated or deprovisioned. "
            "Requires confirmation."
        ),
        "parameters": {
            "user_id": "str (required) – The ID of the deactivated/deprovisioned user to delete",
        },
        "tags": ["delete", "write", "users", "lifecycle"],
    },
    # ─── Applications ────────────────────────────────────────────────────
    {
        "name": "list_applications",
        "category": "applications",
        "description": (
            "List all applications from the Okta organization. "
            "Supports query, filter, pagination, and expand parameters."
        ),
        "parameters": {
            "q": "str – Search by label, property, or link",
            "after": "str – Pagination cursor",
            "limit": "int – Results per page (min 20, max 100)",
            "filter": "str – Filter by status, user.id, group.id, or credentials.signing.kid",
            "expand": "str – Expand user/group profile objects",
            "include_non_deleted": "bool – Include non-deleted applications",
        },
        "tags": ["list", "read", "applications", "apps", "pagination"],
    },
    {
        "name": "get_application",
        "category": "applications",
        "description": "Get an application by ID from the Okta organization.",
        "parameters": {
            "app_id": "str (required) – The ID of the application",
            "expand": "str – Expand user/group profile objects",
        },
        "tags": ["get", "read", "applications", "apps", "lookup"],
    },
    {
        "name": "create_application",
        "category": "applications",
        "description": "Create a new application in the Okta organization.",
        "parameters": {
            "app_config": "dict (required) – Application configuration (name, label, signOnMode, settings, etc.)",
            "activate": "bool – Activate after creation (default: True)",
        },
        "tags": ["create", "write", "applications", "apps"],
    },
    {
        "name": "update_application",
        "category": "applications",
        "description": "Update an application by ID in the Okta organization.",
        "parameters": {
            "app_id": "str (required) – The ID of the application to update",
            "app_config": "dict (required) – Updated application configuration",
        },
        "tags": ["update", "write", "applications", "apps"],
    },
    {
        "name": "delete_application",
        "category": "applications",
        "description": (
            "Delete an application by ID. Requires user confirmation. "
            "If elicitation is unavailable the model should call confirm_delete_application."
        ),
        "parameters": {
            "app_id": "str (required) – The ID of the application to delete",
        },
        "tags": ["delete", "write", "applications", "apps", "lifecycle"],
    },
    {
        "name": "confirm_delete_application",
        "category": "applications",
        "description": (
            "Confirm and execute application deletion (deprecated backward-compat flow). "
            "Only call after the human user has explicitly typed 'DELETE'."
        ),
        "parameters": {
            "app_id": "str (required) – The ID of the application",
            "confirmation": "str (required) – Must be 'DELETE'",
        },
        "tags": ["delete", "write", "applications", "apps", "confirm", "deprecated"],
    },
    {
        "name": "activate_application",
        "category": "applications",
        "description": "Activate an application in the Okta organization.",
        "parameters": {
            "app_id": "str (required) – The ID of the application to activate",
        },
        "tags": ["activate", "write", "applications", "apps", "lifecycle"],
    },
    {
        "name": "deactivate_application",
        "category": "applications",
        "description": "Deactivate an application in the Okta organization. Requires confirmation.",
        "parameters": {
            "app_id": "str (required) – The ID of the application to deactivate",
        },
        "tags": ["deactivate", "write", "applications", "apps", "lifecycle"],
    },
    # ─── Groups ──────────────────────────────────────────────────────────
    {
        "name": "list_groups",
        "category": "groups",
        "description": (
            "List all groups from the Okta organization with pagination support. "
            "Supports search, filter, and query parameters on group profile attributes."
        ),
        "parameters": {
            "search": "str – Search string for specific groups",
            "filter": "str – Filter by Okta group profile attributes",
            "q": "str – Query string to search groups",
            "fetch_all": "bool – Auto-fetch all pages (default: False)",
            "after": "str – Pagination cursor",
            "limit": "int – Results per page (min 20, max 100)",
        },
        "tags": ["list", "read", "groups", "pagination", "search"],
    },
    {
        "name": "get_group",
        "category": "groups",
        "description": "Get a group by ID from the Okta organization.",
        "parameters": {
            "group_id": "str (required) – The ID of the group",
        },
        "tags": ["get", "read", "groups", "lookup"],
    },
    {
        "name": "create_group",
        "category": "groups",
        "description": "Create a new group in the Okta organization.",
        "parameters": {
            "profile": "dict (required) – Group profile (name, description, etc.)",
        },
        "tags": ["create", "write", "groups"],
    },
    {
        "name": "update_group",
        "category": "groups",
        "description": "Update a group by ID with the provided profile.",
        "parameters": {
            "group_id": "str (required) – The ID of the group to update",
            "profile": "dict (required) – New profile fields",
        },
        "tags": ["update", "write", "groups"],
    },
    {
        "name": "delete_group",
        "category": "groups",
        "description": (
            "Delete a group by ID. Requires user confirmation. "
            "If elicitation is unavailable the model should call confirm_delete_group."
        ),
        "parameters": {
            "group_id": "str (required) – The ID of the group to delete",
        },
        "tags": ["delete", "write", "groups", "lifecycle"],
    },
    {
        "name": "confirm_delete_group",
        "category": "groups",
        "description": (
            "Confirm and execute group deletion (deprecated backward-compat flow). "
            "Only call after the human user has explicitly typed 'DELETE'."
        ),
        "parameters": {
            "group_id": "str (required) – The ID of the group",
            "confirmation": "str (required) – Must be 'DELETE'",
        },
        "tags": ["delete", "write", "groups", "confirm", "deprecated"],
    },
    {
        "name": "list_group_users",
        "category": "groups",
        "description": "List all users in a group by group ID with pagination support.",
        "parameters": {
            "group_id": "str (required) – The ID of the group",
            "fetch_all": "bool – Auto-fetch all pages (default: False)",
            "after": "str – Pagination cursor",
            "limit": "int – Results per page (min 20, max 100)",
        },
        "tags": ["list", "read", "groups", "users", "membership", "pagination"],
    },
    {
        "name": "list_group_apps",
        "category": "groups",
        "description": "List all applications assigned to a group by group ID.",
        "parameters": {
            "group_id": "str (required) – The ID of the group",
        },
        "tags": ["list", "read", "groups", "applications", "apps", "membership"],
    },
    {
        "name": "add_user_to_group",
        "category": "groups",
        "description": "Add a user to a group in the Okta organization.",
        "parameters": {
            "group_id": "str (required) – The ID of the group",
            "user_id": "str (required) – The ID of the user to add",
        },
        "tags": ["add", "write", "groups", "users", "membership"],
    },
    {
        "name": "remove_user_from_group",
        "category": "groups",
        "description": "Remove a user from a group in the Okta organization.",
        "parameters": {
            "group_id": "str (required) – The ID of the group",
            "user_id": "str (required) – The ID of the user to remove",
        },
        "tags": ["remove", "write", "groups", "users", "membership"],
    },
    # ─── Policies ────────────────────────────────────────────────────────
    {
        "name": "list_policies",
        "category": "policies",
        "description": (
            "List all policies from the Okta organization. "
            "Requires a policy type: OKTA_SIGN_ON, PASSWORD, MFA_ENROLL, "
            "IDP_DISCOVERY, ACCESS_POLICY, PROFILE_ENROLLMENT, POST_AUTH_SESSION, ENTITY_RISK."
        ),
        "parameters": {
            "type": "str (required) – Policy type",
            "status": "str – ACTIVE or INACTIVE",
            "q": "str – Search policies by name",
            "limit": "int – Results per page (min 20, max 100)",
            "after": "str – Pagination cursor",
        },
        "tags": ["list", "read", "policies", "pagination"],
    },
    {
        "name": "get_policy",
        "category": "policies",
        "description": "Retrieve a specific policy by ID.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
        },
        "tags": ["get", "read", "policies", "lookup"],
    },
    {
        "name": "create_policy",
        "category": "policies",
        "description": (
            "Create a new policy. Supported types: OKTA_SIGN_ON, PASSWORD, MFA_ENROLL, "
            "ACCESS_POLICY, PROFILE_ENROLLMENT, POST_AUTH_SESSION, ENTITY_RISK, "
            "DEVICE_SIGNAL_COLLECTION."
        ),
        "parameters": {
            "policy_data": (
                "dict (required) – Policy config (type, name, description, status, "
                "priority, conditions, settings)"
            ),
        },
        "tags": ["create", "write", "policies"],
    },
    {
        "name": "update_policy",
        "category": "policies",
        "description": "Update an existing policy.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy to update",
            "policy_data": "dict (required) – Updated policy configuration",
        },
        "tags": ["update", "write", "policies"],
    },
    {
        "name": "delete_policy",
        "category": "policies",
        "description": "Delete a policy. Requires user confirmation.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy to delete",
        },
        "tags": ["delete", "write", "policies", "lifecycle"],
    },
    {
        "name": "activate_policy",
        "category": "policies",
        "description": "Activate a policy.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy to activate",
        },
        "tags": ["activate", "write", "policies", "lifecycle"],
    },
    {
        "name": "deactivate_policy",
        "category": "policies",
        "description": "Deactivate a policy. Requires user confirmation.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy to deactivate",
        },
        "tags": ["deactivate", "write", "policies", "lifecycle"],
    },
    {
        "name": "list_policy_rules",
        "category": "policies",
        "description": "List all rules for a specific policy.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
        },
        "tags": ["list", "read", "policies", "rules"],
    },
    {
        "name": "get_policy_rule",
        "category": "policies",
        "description": "Retrieve a specific policy rule.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_id": "str (required) – The ID of the rule",
        },
        "tags": ["get", "read", "policies", "rules", "lookup"],
    },
    {
        "name": "create_policy_rule",
        "category": "policies",
        "description": "Create a new rule for a policy.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_data": "dict (required) – Rule config (name, priority, status, conditions, actions)",
        },
        "tags": ["create", "write", "policies", "rules"],
    },
    {
        "name": "update_policy_rule",
        "category": "policies",
        "description": "Update an existing policy rule.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_id": "str (required) – The ID of the rule to update",
            "rule_data": "dict (required) – Updated rule configuration",
        },
        "tags": ["update", "write", "policies", "rules"],
    },
    {
        "name": "delete_policy_rule",
        "category": "policies",
        "description": "Delete a policy rule. Requires user confirmation.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_id": "str (required) – The ID of the rule to delete",
        },
        "tags": ["delete", "write", "policies", "rules", "lifecycle"],
    },
    {
        "name": "activate_policy_rule",
        "category": "policies",
        "description": "Activate a policy rule.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_id": "str (required) – The ID of the rule to activate",
        },
        "tags": ["activate", "write", "policies", "rules", "lifecycle"],
    },
    {
        "name": "deactivate_policy_rule",
        "category": "policies",
        "description": "Deactivate a policy rule. Requires user confirmation.",
        "parameters": {
            "policy_id": "str (required) – The ID of the policy",
            "rule_id": "str (required) – The ID of the rule to deactivate",
        },
        "tags": ["deactivate", "write", "policies", "rules", "lifecycle"],
    },
    # ─── System Logs ─────────────────────────────────────────────────────
    {
        "name": "get_logs",
        "category": "system_logs",
        "description": (
            "Retrieve system logs from the Okta organization with pagination support. "
            "Supports time-range filtering, query, and filter expressions."
        ),
        "parameters": {
            "fetch_all": "bool – Auto-fetch all pages (default: False)",
            "after": "str – Pagination cursor",
            "limit": "int – Results per page (min 20, max 100)",
            "since": "str – Filter logs since this ISO 8601 timestamp",
            "until": "str – Filter logs until this ISO 8601 timestamp",
            "filter": "str – Filter expression for log events",
            "q": "str – Query string to search log events",
        },
        "tags": ["list", "read", "system_logs", "logs", "audit", "events", "pagination"],
    },
    # ─── Device Assurance ────────────────────────────────────────────────
    {
        "name": "list_device_assurance_policies",
        "category": "device_assurance",
        "description": "List all Device Assurance Policies in the Okta organization.",
        "parameters": {},
        "tags": ["list", "read", "device_assurance", "policy"],
    },
    {
        "name": "get_device_assurance_policy",
        "category": "device_assurance",
        "description": "Retrieve a specific Device Assurance Policy by ID.",
        "parameters": {
            "device_assurance_id": "str (required) – The ID of the device assurance policy",
        },
        "tags": ["get", "read", "device_assurance", "policy"],
    },
    {
        "name": "create_device_assurance_policy",
        "category": "device_assurance",
        "description": "Create a new Device Assurance Policy with platform-specific requirements.",
        "parameters": {
            "policy_data": "dict (required) – Policy config: name, platform (ANDROID|IOS|MACOS|WINDOWS|CHROMEOS), osVersion, diskEncryptionType, secureHardwarePresent, screenLockType, jailbreak",
        },
        "tags": ["create", "write", "device_assurance", "policy"],
    },
    {
        "name": "replace_device_assurance_policy",
        "category": "device_assurance",
        "description": "Replace (fully update) an existing Device Assurance Policy.",
        "parameters": {
            "device_assurance_id": "str (required) – The ID of the policy to update",
            "policy_data": "dict (required) – Complete updated policy configuration",
        },
        "tags": ["replace", "update", "write", "device_assurance", "policy"],
    },
    {
        "name": "delete_device_assurance_policy",
        "category": "device_assurance",
        "description": "Delete a Device Assurance Policy. Requires user confirmation.",
        "parameters": {
            "device_assurance_id": "str (required) – The ID of the policy to delete",
        },
        "tags": ["delete", "write", "device_assurance", "policy"],
    },
    # ─── Brands ──────────────────────────────────────────────────────────
    {
        "name": "list_brands",
        "category": "brands",
        "description": (
            "List all brands in the Okta organization with pagination support. "
            "Supports search, expand, and cursor-based pagination."
        ),
        "parameters": {
            "expand": "List[str] – Embed additional metadata: 'themes', 'domains', 'emailDomain'",
            "after": "str – Pagination cursor from previous response",
            "limit": "int – Max brands per page (1–200, default 20)",
            "q": "str – Case-insensitive search by brand name",
            "fetch_all": "bool – Auto-fetch all pages (default: False)",
        },
        "tags": ["list", "read", "brands", "customization", "pagination"],
    },
    {
        "name": "get_brand",
        "category": "brands",
        "description": "Retrieve a specific brand by its ID.",
        "parameters": {
            "brand_id": "str (required) – The unique identifier of the brand",
            "expand": "List[str] – Embed additional metadata: 'themes', 'domains', 'emailDomain'",
        },
        "tags": ["get", "read", "brands", "customization"],
    },
    {
        "name": "create_brand",
        "category": "brands",
        "description": "Create a new brand controlling sign-in page, error pages, email templates, and dashboard look-and-feel.",
        "parameters": {
            "name": "str (required) – Display name for the new brand (must be unique)",
        },
        "tags": ["create", "write", "brands", "customization"],
    },
    {
        "name": "replace_brand",
        "category": "brands",
        "description": "Replace (fully update) a brand by its ID including privacy policy, locale, and default app settings.",
        "parameters": {
            "brand_id": "str (required) – The brand to update",
            "name": "str (required) – New display name",
            "agree_to_custom_privacy_policy": "bool – Required when providing custom_privacy_policy_url",
            "custom_privacy_policy_url": "str – HTTPS URL of custom privacy policy",
            "remove_powered_by_okta": "bool – Remove 'Powered by Okta' footer",
            "locale": "str – IETF BCP 47 language tag (e.g. 'en', 'fr')",
            "email_domain_id": "str – ID of email domain to associate",
            "default_app": "dict – Default app config: appInstanceId, appLinkName, classicApplicationUri",
        },
        "tags": ["replace", "update", "write", "brands", "customization"],
    },
    {
        "name": "delete_brand",
        "category": "brands",
        "description": "Delete a brand by its ID. Requires user confirmation.",
        "parameters": {
            "brand_id": "str (required) – The brand to delete",
        },
        "tags": ["delete", "write", "brands", "customization"],
    },
    {
        "name": "list_brand_domains",
        "category": "brands",
        "description": "List all custom domains associated with a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand to list domains for",
        },
        "tags": ["list", "read", "brands", "domains", "customization"],
    },
    # ─── Custom Domains ──────────────────────────────────────────────────
    {
        "name": "list_custom_domains",
        "category": "custom_domains",
        "description": "List all custom domains in the Okta organization.",
        "parameters": {},
        "tags": ["list", "read", "custom_domains", "customization"],
    },
    {
        "name": "create_custom_domain",
        "category": "custom_domains",
        "description": "Create a new custom domain. Returns DNS records (TXT + CNAME) to configure before verification.",
        "parameters": {
            "domain": "str (required) – Fully qualified domain name (e.g. 'login.example.com')",
            "certificate_source_type": "str (required) – 'MANUAL' or 'OKTA_MANAGED'",
        },
        "tags": ["create", "write", "custom_domains", "customization", "dns"],
    },
    {
        "name": "get_custom_domain",
        "category": "custom_domains",
        "description": "Retrieve a custom domain by its ID. Use 'default' for the org's default subdomain.",
        "parameters": {
            "domain_id": "str (required) – Unique ID of the domain or 'default'",
        },
        "tags": ["get", "read", "custom_domains", "customization"],
    },
    {
        "name": "replace_custom_domain",
        "category": "custom_domains",
        "description": "Replace the brand associated with a custom domain.",
        "parameters": {
            "domain_id": "str (required) – ID of the domain to update",
            "brand_id": "str (required) – ID of the brand to associate",
        },
        "tags": ["replace", "update", "write", "custom_domains", "customization"],
    },
    {
        "name": "delete_custom_domain",
        "category": "custom_domains",
        "description": "Delete a custom domain by its ID.",
        "parameters": {
            "domain_id": "str (required) – ID of the domain to delete",
        },
        "tags": ["delete", "write", "custom_domains", "customization"],
    },
    {
        "name": "upsert_custom_domain_certificate",
        "category": "custom_domains",
        "description": "Upload or renew the TLS certificate for a MANUAL custom domain.",
        "parameters": {
            "domain_id": "str (required) – ID of the domain",
            "certificate": "str (required) – PEM-encoded TLS leaf certificate",
            "certificate_chain": "str (required) – PEM-encoded certificate chain",
            "private_key_file_path": "str (required) – Path to PEM-encoded RSA private key file",
        },
        "tags": ["upsert", "write", "custom_domains", "customization", "tls", "certificate"],
    },
    {
        "name": "verify_custom_domain",
        "category": "custom_domains",
        "description": "Verify a custom domain by checking its DNS records.",
        "parameters": {
            "domain_id": "str (required) – ID of the domain to verify",
        },
        "tags": ["verify", "write", "custom_domains", "customization", "dns"],
    },
    # ─── Themes ──────────────────────────────────────────────────────────
    {
        "name": "list_brand_themes",
        "category": "themes",
        "description": "List all themes for a brand. Currently each Okta org supports one theme per brand.",
        "parameters": {
            "brand_id": "str (required) – The brand to list themes for",
        },
        "tags": ["list", "read", "themes", "customization", "brands"],
    },
    {
        "name": "get_brand_theme",
        "category": "themes",
        "description": "Retrieve a specific theme by brand ID and theme ID.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
        },
        "tags": ["get", "read", "themes", "customization", "brands"],
    },
    {
        "name": "replace_brand_theme",
        "category": "themes",
        "description": "Replace a theme's colours and touchpoint variants (sign-in page, dashboard, error page, email).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
            "primary_color_hex": "str (required) – Primary colour hex (e.g. '#1662dd')",
            "secondary_color_hex": "str (required) – Secondary colour hex",
            "sign_in_page_touch_point_variant": "str (required) – BACKGROUND_IMAGE | BACKGROUND_SECONDARY_COLOR | OKTA_DEFAULT",
            "end_user_dashboard_touch_point_variant": "str (required) – FULL_THEME | LOGO_ON_FULL_WHITE_BACKGROUND | OKTA_DEFAULT | WHITE_LOGO_BACKGROUND",
            "error_page_touch_point_variant": "str (required) – BACKGROUND_IMAGE | BACKGROUND_SECONDARY_COLOR | OKTA_DEFAULT",
            "email_template_touch_point_variant": "str (required) – FULL_THEME | OKTA_DEFAULT",
        },
        "tags": ["replace", "update", "write", "themes", "customization", "brands", "colors"],
    },
    {
        "name": "upload_brand_theme_logo",
        "category": "themes",
        "description": "Upload and replace the logo for a theme. Must be PNG, JPG, or GIF under 100 kB.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
            "file_path": "str (required) – Absolute path to the image file",
        },
        "tags": ["upload", "write", "themes", "customization", "logo", "image"],
    },
    {
        "name": "delete_brand_theme_logo",
        "category": "themes",
        "description": "Delete the custom logo for a theme. Falls back to the default Okta logo.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
        },
        "tags": ["delete", "write", "themes", "customization", "logo"],
    },
    {
        "name": "upload_brand_theme_favicon",
        "category": "themes",
        "description": "Upload and replace the favicon for a theme. Must be PNG, JPG, or GIF under 2 MB.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
            "file_path": "str (required) – Absolute path to the image file",
        },
        "tags": ["upload", "write", "themes", "customization", "favicon", "image"],
    },
    {
        "name": "delete_brand_theme_favicon",
        "category": "themes",
        "description": "Delete the custom favicon for a theme. Falls back to the default Okta favicon.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
        },
        "tags": ["delete", "write", "themes", "customization", "favicon"],
    },
    {
        "name": "upload_brand_theme_background_image",
        "category": "themes",
        "description": "Upload and replace the background image for a theme. Must be PNG, JPG, or GIF under 2 MB.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
            "file_path": "str (required) – Absolute path to the image file",
        },
        "tags": ["upload", "write", "themes", "customization", "background", "image"],
    },
    {
        "name": "delete_brand_theme_background_image",
        "category": "themes",
        "description": "Delete the background image for a theme. Falls back to default appearance.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "theme_id": "str (required) – The theme identifier",
        },
        "tags": ["delete", "write", "themes", "customization", "background"],
    },
    # ─── Custom Pages ────────────────────────────────────────────────────
    {
        "name": "get_error_page_resources",
        "category": "custom_pages",
        "description": "Retrieve the error page sub-resource links for a brand (customized, default, preview).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "expand": "List[str] – Sub-resources to embed: 'default', 'customized', 'customizedUrl', 'preview', 'previewUrl'",
        },
        "tags": ["get", "read", "custom_pages", "error_page", "customization"],
    },
    {
        "name": "get_customized_error_page",
        "category": "custom_pages",
        "description": "Retrieve the customized error page shown to end-users in the live environment.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "error_page", "customization"],
    },
    {
        "name": "replace_customized_error_page",
        "category": "custom_pages",
        "description": "Replace the customized error page HTML for a brand's live environment.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "page_content": "str – Full HTML content with Okta template variables",
            "csp_mode": "str – CSP mode: 'enforced', 'report_only', 'disabled'",
            "csp_report_uri": "str – URI for CSP violation reports",
            "csp_src_list": "List[str] – Allowed source origins for CSP",
        },
        "tags": ["replace", "write", "custom_pages", "error_page", "customization"],
    },
    {
        "name": "delete_customized_error_page",
        "category": "custom_pages",
        "description": "Delete the customized error page for a brand. Reverts to Okta default.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["delete", "write", "custom_pages", "error_page", "customization"],
    },
    {
        "name": "get_default_error_page",
        "category": "custom_pages",
        "description": "Retrieve the default (Okta-provided) error page for a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "error_page", "default", "customization"],
    },
    {
        "name": "get_preview_error_page",
        "category": "custom_pages",
        "description": "Retrieve the preview error page for testing changes before going live.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "error_page", "preview", "customization"],
    },
    {
        "name": "replace_preview_error_page",
        "category": "custom_pages",
        "description": "Replace the preview error page HTML for sandbox testing.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "page_content": "str – Full HTML content with Okta template variables",
            "csp_mode": "str – CSP mode: 'enforced', 'report_only', 'disabled'",
            "csp_report_uri": "str – URI for CSP violation reports",
            "csp_src_list": "List[str] – Allowed source origins for CSP",
        },
        "tags": ["replace", "write", "custom_pages", "error_page", "preview", "customization"],
    },
    {
        "name": "delete_preview_error_page",
        "category": "custom_pages",
        "description": "Delete the preview error page for a brand. Falls back to default.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["delete", "write", "custom_pages", "error_page", "preview", "customization"],
    },
    {
        "name": "get_sign_in_page_resources",
        "category": "custom_pages",
        "description": "Retrieve the sign-in page sub-resource links for a brand (customized, default, preview).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "expand": "List[str] – Sub-resources to embed: 'default', 'customized', 'customizedUrl', 'preview', 'previewUrl'",
        },
        "tags": ["get", "read", "custom_pages", "sign_in_page", "customization"],
    },
    {
        "name": "get_customized_sign_in_page",
        "category": "custom_pages",
        "description": "Retrieve the customized sign-in page shown to end-users in the live environment.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "sign_in_page", "customization"],
    },
    {
        "name": "replace_customized_sign_in_page",
        "category": "custom_pages",
        "description": "Replace the customized sign-in page HTML, widget version, and widget behaviour for a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "page_content": "str – Full HTML content",
            "widget_version": "str – Sign-In Widget version (e.g. '*', '^5', '7')",
            "widget_customizations": "dict – Widget fields: sign_in_label, forgot_password_label, etc.",
            "csp_mode": "str – CSP mode: 'enforced', 'report_only', 'disabled'",
        },
        "tags": ["replace", "write", "custom_pages", "sign_in_page", "widget", "customization"],
    },
    {
        "name": "delete_customized_sign_in_page",
        "category": "custom_pages",
        "description": "Delete the customized sign-in page for a brand. Reverts to Okta default.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["delete", "write", "custom_pages", "sign_in_page", "customization"],
    },
    {
        "name": "get_default_sign_in_page",
        "category": "custom_pages",
        "description": "Retrieve the default (Okta-provided) sign-in page for a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "sign_in_page", "default", "customization"],
    },
    {
        "name": "get_preview_sign_in_page",
        "category": "custom_pages",
        "description": "Retrieve the preview sign-in page for testing changes before going live.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "sign_in_page", "preview", "customization"],
    },
    {
        "name": "replace_preview_sign_in_page",
        "category": "custom_pages",
        "description": "Replace the preview sign-in page HTML, widget version, and behaviour for sandbox testing.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "page_content": "str – Full HTML content",
            "widget_version": "str – Sign-In Widget version",
            "widget_customizations": "dict – Widget customisation fields",
            "csp_mode": "str – CSP mode: 'enforced', 'report_only', 'disabled'",
        },
        "tags": ["replace", "write", "custom_pages", "sign_in_page", "preview", "widget", "customization"],
    },
    {
        "name": "delete_preview_sign_in_page",
        "category": "custom_pages",
        "description": "Delete the preview sign-in page for a brand. Falls back to default.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["delete", "write", "custom_pages", "sign_in_page", "preview", "customization"],
    },
    {
        "name": "list_sign_in_widget_versions",
        "category": "custom_pages",
        "description": "List all available Okta Sign-In Widget versions for a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["list", "read", "custom_pages", "sign_in_page", "widget", "customization"],
    },
    {
        "name": "get_sign_out_page_settings",
        "category": "custom_pages",
        "description": "Retrieve the sign-out page settings controlling redirect behaviour after sign-out.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
        },
        "tags": ["get", "read", "custom_pages", "sign_out_page", "customization"],
    },
    {
        "name": "replace_sign_out_page_settings",
        "category": "custom_pages",
        "description": "Replace sign-out page settings. Controls redirect destination after sign-out.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "type": "str (required) – 'OKTA_DEFAULT' or 'EXTERNALLY_HOSTED'",
            "url": "str – Redirect URL (required when type is 'EXTERNALLY_HOSTED')",
        },
        "tags": ["replace", "write", "custom_pages", "sign_out_page", "customization"],
    },
    # ─── Custom Templates (Email) ────────────────────────────────────────
    {
        "name": "list_email_templates",
        "category": "custom_templates",
        "description": "List all email templates for a brand (UserActivation, ForgotPassword, etc.).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "expand": "List[str] – Embed: 'settings', 'customizationCount'",
        },
        "tags": ["list", "read", "custom_templates", "email", "customization"],
    },
    {
        "name": "get_email_template",
        "category": "custom_templates",
        "description": "Retrieve a single email template for a brand.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name (e.g. 'UserActivation', 'ForgotPassword')",
            "expand": "List[str] – Embed: 'settings', 'customizationCount'",
        },
        "tags": ["get", "read", "custom_templates", "email", "customization"],
    },
    {
        "name": "list_email_customizations",
        "category": "custom_templates",
        "description": "List all language customizations for an email template.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
        },
        "tags": ["list", "read", "custom_templates", "email", "customization"],
    },
    {
        "name": "create_email_customization",
        "category": "custom_templates",
        "description": "Create a new language customization for an email template.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "language": "str (required) – IETF BCP 47 language tag (e.g. 'en', 'fr')",
            "subject": "str (required) – Email subject line (supports Okta template variables)",
            "body": "str (required) – Full HTML body with required template variables",
            "is_default": "bool – Whether this is the default customization",
        },
        "tags": ["create", "write", "custom_templates", "email", "customization"],
    },
    {
        "name": "get_email_customization",
        "category": "custom_templates",
        "description": "Retrieve a specific email customization by its ID.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "customization_id": "str (required) – The customization ID",
        },
        "tags": ["get", "read", "custom_templates", "email", "customization"],
    },
    {
        "name": "replace_email_customization",
        "category": "custom_templates",
        "description": "Replace an existing email customization (full update).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "customization_id": "str (required) – The customization to replace",
            "language": "str (required) – IETF BCP 47 language tag",
            "subject": "str (required) – Updated email subject",
            "body": "str (required) – Updated full HTML body",
            "is_default": "bool – Set as default customization",
        },
        "tags": ["replace", "update", "write", "custom_templates", "email", "customization"],
    },
    {
        "name": "delete_email_customization",
        "category": "custom_templates",
        "description": "Delete a specific email customization (language variant).",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "customization_id": "str (required) – The customization to delete",
            "language": "str – Language of the customization (for confirmation prompt)",
        },
        "tags": ["delete", "write", "custom_templates", "email", "customization"],
    },
    {
        "name": "delete_all_email_customizations",
        "category": "custom_templates",
        "description": "Delete ALL customizations for an email template. Reverts to Okta built-in defaults.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template whose customizations will be deleted",
        },
        "tags": ["delete", "write", "custom_templates", "email", "customization"],
    },
    {
        "name": "get_email_customization_preview",
        "category": "custom_templates",
        "description": "Preview a rendered email customization with sample values replacing template variables.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "customization_id": "str (required) – The customization to preview",
        },
        "tags": ["get", "read", "custom_templates", "email", "preview", "customization"],
    },
    {
        "name": "get_email_default_content",
        "category": "custom_templates",
        "description": "Retrieve the Okta default (unmodified) content for an email template.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "language": "str – IETF BCP 47 language tag (defaults to API user's language)",
        },
        "tags": ["get", "read", "custom_templates", "email", "default", "customization"],
    },
    {
        "name": "get_email_default_content_preview",
        "category": "custom_templates",
        "description": "Preview the rendered Okta default content for an email template with sample values.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "language": "str – IETF BCP 47 language tag",
        },
        "tags": ["get", "read", "custom_templates", "email", "default", "preview", "customization"],
    },
    {
        "name": "get_email_settings",
        "category": "custom_templates",
        "description": "Retrieve the email settings (recipient configuration) for a template.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
        },
        "tags": ["get", "read", "custom_templates", "email", "settings", "customization"],
    },
    {
        "name": "replace_email_settings",
        "category": "custom_templates",
        "description": "Replace the email settings for a template. Controls which users receive the email.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name",
            "recipients": "str (required) – 'ALL_USERS', 'ADMINS_ONLY', or 'NO_USERS'",
        },
        "tags": ["replace", "write", "custom_templates", "email", "settings", "customization"],
    },
    {
        "name": "send_test_email",
        "category": "custom_templates",
        "description": "Send a test email for a template to the current API user.",
        "parameters": {
            "brand_id": "str (required) – The brand identifier",
            "template_name": "str (required) – Template name (e.g. 'UserActivation')",
            "language": "str – IETF BCP 47 language tag for which customization to test",
        },
        "tags": ["write", "custom_templates", "email", "test", "customization"],
    },
    # ─── Email Domains ───────────────────────────────────────────────────
    {
        "name": "list_email_domains",
        "category": "email_domains",
        "description": "List all email domains in the Okta organization with validation status and DNS records.",
        "parameters": {
            "expand_brands": "bool – Embed associated Brand objects (default: False)",
        },
        "tags": ["list", "read", "email_domains", "customization"],
    },
    {
        "name": "create_email_domain",
        "category": "email_domains",
        "description": "Create a new email domain. Returns DNS records to publish at your DNS provider.",
        "parameters": {
            "brand_id": "str (required) – Brand to associate with this email domain",
            "domain": "str (required) – Custom domain (e.g. 'yourcompany.com')",
            "display_name": "str (required) – Sender name in email clients (e.g. 'Acme IT Support')",
            "user_name": "str (required) – Local part of sender address (e.g. 'noreply')",
            "validation_subdomain": "str – Subdomain for mail CNAME records (default: 'mail')",
        },
        "tags": ["create", "write", "email_domains", "customization", "dns"],
    },
    {
        "name": "get_email_domain",
        "category": "email_domains",
        "description": "Retrieve an email domain by its ID.",
        "parameters": {
            "email_domain_id": "str (required) – ID of the email domain",
            "expand_brands": "bool – Embed associated Brand objects (default: False)",
        },
        "tags": ["get", "read", "email_domains", "customization"],
    },
    {
        "name": "replace_email_domain",
        "category": "email_domains",
        "description": "Replace the sender display name and username for an email domain.",
        "parameters": {
            "email_domain_id": "str (required) – ID of the email domain",
            "display_name": "str (required) – New sender display name",
            "user_name": "str (required) – New local part of sender address",
        },
        "tags": ["replace", "update", "write", "email_domains", "customization"],
    },
    {
        "name": "delete_email_domain",
        "category": "email_domains",
        "description": "Delete an email domain by its ID.",
        "parameters": {
            "email_domain_id": "str (required) – ID of the email domain to delete",
        },
        "tags": ["delete", "write", "email_domains", "customization"],
    },
    {
        "name": "verify_email_domain",
        "category": "email_domains",
        "description": "Verify an email domain by checking its DNS records.",
        "parameters": {
            "email_domain_id": "str (required) – ID of the email domain to verify",
        },
        "tags": ["verify", "write", "email_domains", "customization", "dns"],
    },
]

# Pre-built category index for fast filter
CATEGORIES = sorted({tool["category"] for tool in TOOL_CATALOG})

# Pre-built name lookup for validation
TOOL_NAMES = {tool["name"] for tool in TOOL_CATALOG}

# ─── Lazy-loading infrastructure ─────────────────────────────────────
# Maps category names to their importable module paths.
# Importing a module registers its @mcp.tool()-decorated functions.
CATEGORY_MODULES: dict[str, str] = {
    "users": "okta_mcp_server.tools.users.users",
    "groups": "okta_mcp_server.tools.groups.groups",
    "applications": "okta_mcp_server.tools.applications.applications",
    "policies": "okta_mcp_server.tools.policies.policies",
    "system_logs": "okta_mcp_server.tools.system_logs.system_logs",
    "device_assurance": "okta_mcp_server.tools.device_assurance.device_assurance",
    "brands": "okta_mcp_server.tools.customization.brands.brands",
    "custom_domains": "okta_mcp_server.tools.customization.custom_domains.custom_domains",
    "themes": "okta_mcp_server.tools.customization.themes.themes",
    "custom_pages": "okta_mcp_server.tools.customization.custom_pages.custom_pages",
    "custom_templates": "okta_mcp_server.tools.customization.custom_templates.custom_templates",
    "email_domains": "okta_mcp_server.tools.customization.email_domains.email_domains",
}

# Tracks which categories have already been loaded into the MCP server.
_loaded_categories: set[str] = set()

# Tracks which tool names were registered per category (for unloading).
_category_tool_names: dict[str, list[str]] = {}

# ─── Usage tracking infrastructure ───────────────────────────────────
# How many times each tool has been called this session.
_usage_counts: dict[str, int] = {}

# Ordered record of (tool_name, turn_number) for conversation pattern analysis.
_call_sequence: list[tuple[str, int]] = []

# Monotonically increasing turn counter — incremented each time search_tools
# is invoked (a reliable proxy for "LLM is starting a new subtask").
_turn_number: int = 0

# Last turn each category had a tool called within it.
_category_last_turn: dict[str, int] = {}

# Tool name → category lookup built once from TOOL_CATALOG.
_tool_category: dict[str, str] = {t["name"]: t["category"] for t in TOOL_CATALOG}


def record_tool_call(tool_name: str) -> None:
    """Record that a tool was called. Called by the MCP interceptor in server.py."""
    global _turn_number
    _usage_counts[tool_name] = _usage_counts.get(tool_name, 0) + 1
    _call_sequence.append((tool_name, _turn_number))
    cat = _tool_category.get(tool_name)
    if cat:
        _category_last_turn[cat] = _turn_number


def increment_turn() -> int:
    """Increment the turn counter. Called at the start of each search_tools invocation."""
    global _turn_number
    _turn_number += 1
    return _turn_number


def _recommend(cat: str, total_calls: int, last_turn: int, current_turn: int) -> str:
    """Return a plain-English recommendation for whether to keep the category loaded."""
    turns_since = current_turn - last_turn
    # Used very recently — almost certainly needed again soon
    if turns_since <= 1:
        return "keep_loaded — used in the last turn"
    # High call count — clearly a primary category for this session
    if total_calls >= 4:
        return "keep_loaded — called frequently this session"
    # Used within last 3 turns and called more than once — likely recurring
    if turns_since <= 3 and total_calls >= 2:
        return "keep_loaded — recurring use pattern detected"
    # Low use, a while ago
    if turns_since >= 4 and total_calls == 1:
        return "safe_to_unload — used once, not seen recently"
    # Moderate staleness
    if turns_since >= 3:
        return "consider_unloading — not used in last 3 turns"
    return "keep_loaded"


def _detect_conversation_pattern(cat: str) -> str:
    """Analyse the call sequence to detect whether a category shows an alternating pattern.

    An alternating pattern (cat used → other things → cat used again) strongly predicts
    the category will be needed again even if it wasn't called recently.
    """
    # Pull just the category sequence (not individual tools)
    category_sequence = [
        _tool_category.get(name)
        for name, _ in _call_sequence
        if _tool_category.get(name)
    ]
    # Find occurrences of this category in the sequence
    positions = [i for i, c in enumerate(category_sequence) if c == cat]
    if len(positions) < 2:
        return "single_use"
    # Check if there's something between the first and last occurrence
    first, last = positions[0], positions[-1]
    interleaved = set(category_sequence[first:last + 1]) - {cat}
    if interleaved:
        return "alternating — likely to be needed again"
    return "consecutive"


def get_usage_summary() -> dict:
    """Return per-category usage stats and LLM-actionable recommendations.

    Included in every search_tools and unload_tools response so the LLM can
    reason about which loaded categories to keep vs unload.
    """
    current_turn = _turn_number
    summary: dict = {"current_turn": current_turn, "categories": {}}

    # Aggregate call counts per category
    category_calls: dict[str, int] = {}
    category_tool_counts: dict[str, dict[str, int]] = {}
    for tool_name, count in _usage_counts.items():
        cat = _tool_category.get(tool_name)
        if not cat:
            continue
        category_calls[cat] = category_calls.get(cat, 0) + count
        if cat not in category_tool_counts:
            category_tool_counts[cat] = {}
        category_tool_counts[cat][tool_name] = count

    for cat, total_calls in category_calls.items():
        last_turn = _category_last_turn.get(cat, 0)
        turns_since = current_turn - last_turn
        pattern = _detect_conversation_pattern(cat)
        recommendation = _recommend(cat, total_calls, last_turn, current_turn)

        # Override recommendation if alternating pattern found
        if "alternating" in pattern and "unload" in recommendation:
            recommendation = "keep_loaded — alternating use pattern predicts future need"

        summary["categories"][cat] = {
            "total_calls": total_calls,
            "tools_used": category_tool_counts.get(cat, {}),
            "last_used_turn": last_turn,
            "turns_since_last_use": turns_since,
            "conversation_pattern": pattern,
            "recommendation": recommendation,
        }

    # Add a sorted list so the LLM sees highest-priority unload candidates first
    summary["unload_candidates"] = [
        cat for cat, data in sorted(
            summary["categories"].items(),
            key=lambda kv: kv[1]["total_calls"]
        )
        if "unload" in data["recommendation"]
    ]

    return summary


def reset_usage_stats() -> None:
    """Reset all usage tracking state. Called from reset_loaded_categories for test isolation."""
    global _turn_number
    _usage_counts.clear()
    _call_sequence.clear()
    _category_last_turn.clear()
    _turn_number = 0


def load_categories(categories: set[str]) -> set[str]:
    """Lazily import tool modules for the given categories.

    Only imports modules that haven't been loaded yet. Importing a module
    causes its ``@mcp.tool()``-decorated functions to be registered with
    the FastMCP instance.

    Returns:
        The set of category names that were newly loaded by this call.
    """
    import importlib
    import sys

    from loguru import logger

    from okta_mcp_server.server import mcp

    newly_loaded: set[str] = set()
    for cat in categories:
        if cat in _loaded_categories:
            continue
        module_path = CATEGORY_MODULES.get(cat)
        if module_path is None:
            logger.warning(f"No module registered for category '{cat}'")
            continue
        try:
            # Snapshot tool names before import
            before = {t.name for t in mcp._tool_manager.list_tools()}

            # Remove from sys.modules so re-import after unload works
            if module_path in sys.modules:
                del sys.modules[module_path]

            importlib.import_module(module_path)

            # Diff to find which tools this module registered
            after = {t.name for t in mcp._tool_manager.list_tools()}
            new_tools = sorted(after - before)
            _category_tool_names[cat] = new_tools

            _loaded_categories.add(cat)
            newly_loaded.add(cat)
            logger.info(f"Lazy-loaded tool category '{cat}' from {module_path} ({len(new_tools)} tools)")
        except Exception as exc:
            logger.error(f"Failed to load category '{cat}': {exc}")
    return newly_loaded


def unload_categories(categories: set[str]) -> dict[str, list[str]]:
    """Unload tool categories by removing their tools from the MCP server.

    Calls ``mcp.remove_tool(name)`` for every tool that was registered
    when the category was loaded, then removes the category from the
    loaded-tracking set.

    Returns:
        A dict mapping each successfully unloaded category to the list of
        tool names that were removed.
    """
    from loguru import logger

    from okta_mcp_server.server import mcp

    unloaded: dict[str, list[str]] = {}
    for cat in categories:
        if cat not in _loaded_categories:
            logger.info(f"Category '{cat}' is not loaded, skipping unload")
            continue
        tool_names = _category_tool_names.get(cat, [])
        removed: list[str] = []
        for name in tool_names:
            try:
                mcp.remove_tool(name)
                removed.append(name)
            except Exception as exc:
                logger.warning(f"Could not remove tool '{name}': {exc}")
        _loaded_categories.discard(cat)
        _category_tool_names.pop(cat, None)
        unloaded[cat] = removed
        logger.info(f"Unloaded category '{cat}': removed {len(removed)} tools")
    return unloaded


def get_loaded_categories() -> set[str]:
    """Return the set of categories that have been loaded so far."""
    return set(_loaded_categories)


def reset_loaded_categories() -> None:
    """Reset the loaded state (for testing purposes).

    Removes ALL tools in TOOL_CATALOG from the MCP server, not just the ones
    tracked in _category_tool_names.  This broader cleanup is necessary because
    some test modules (e.g. elicitation tests) import tool modules directly,
    causing @mcp.tool() to fire without going through load_categories(),
    which would leave tools registered but untracked.
    """
    from okta_mcp_server.server import mcp

    # Remove every catalog tool that might be registered — tracked or not.
    for tool in TOOL_CATALOG:
        try:
            mcp.remove_tool(tool["name"])
        except Exception:
            pass  # tool was never registered or already removed — that's fine
    _loaded_categories.clear()
    _category_tool_names.clear()
    reset_usage_stats()
