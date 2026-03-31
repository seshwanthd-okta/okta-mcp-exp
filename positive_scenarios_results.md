# MCP SERVER TEST SCENARIOS - THEMES, CUSTOM EMAIL TEMPLATES, EMAIL DOMAINS

## 3.1.2 Themes - Positive Scenarios

| Test ID | Result | Evidence |
|---|---|---|
| THEME-POS-001 | ✅ PASS | Returned 1 theme for brand `testsesh`: ID `thewqkqshkapYPaQT1d7`, Primary `#1662dd`, Secondary `#ebebed`, Sign-In `BACKGROUND_IMAGE`, Dashboard `FULL_THEME`, Error Page `BACKGROUND_IMAGE`, Email Template `FULL_THEME`, Loading Page `NONE`, Okta default logo, Favicon from `oktapreview.com` |
| THEME-POS-002 | ✅ PASS | `get_theme(thewqkqshkapYPaQT1d7)` returned full config: Primary `#1662dd`, Secondary `#ebebed`, Sign-In `BACKGROUND_IMAGE`, Dashboard `FULL_THEME`, Error Page `BACKGROUND_IMAGE`, Email Template `FULL_THEME`, Loading Page `NONE`, Logo via CDN, Favicon from `oktapreview.com` |
| THEME-POS-003 | ✅ PASS | Primary color updated from `#e63946` → `#ff0000`. All other properties (Secondary, Sign-In, Dashboard, Error Page, Email Template, Loading Page) retained unchanged |
| THEME-POS-004 | ✅ PASS | Multi-property update applied: Primary `#ff0000`, Secondary `#0000ff`, Sign-In `BACKGROUND_IMAGE`, Dashboard `FULL_THEME`, Error Page `OKTA_DEFAULT`, Email Template `OKTA_DEFAULT`, Loading Page `OKTA_DEFAULT` |
| THEME-POS-005 | ❌ FAIL | Okta HTTP 400 `E0000019` — SDK bug: `_files` dict is not forwarded through `_request_executor.create_request()`, so file bytes are never sent. Fix: patch upload functions to use `aiohttp` multipart/form-data directly, bypassing the SDK |
| THEME-POS-006 | ❌ FAIL | Same root cause as THEME-POS-005 — `_files` dict dropped by legacy request path; `favicon.ico` content never reaches Okta. Fix: use `aiohttp` multipart directly |
| THEME-POS-007 | ❌ FAIL | Same root cause as THEME-POS-005/006 — `bg.jpg` bytes never forwarded through `_request_executor.create_request()`. Fix: use `aiohttp` multipart directly |
| THEME-POS-008 | ✅ PASS | Sign-In variant set to `BACKGROUND_IMAGE`. All other properties retained: Primary `#ff0000`, Secondary `#0000ff`, Dashboard `FULL_THEME`, Error Page `OKTA_DEFAULT`, Email Template `OKTA_DEFAULT`, Loading Page `OKTA_DEFAULT` |
| THEME-POS-009 | ✅ PASS | Dashboard variant confirmed as `FULL_THEME`. All other properties retained: Primary `#ff0000`, Secondary `#0000ff`, Sign-In `BACKGROUND_IMAGE`, Error Page `OKTA_DEFAULT`, Email Template `OKTA_DEFAULT`, Loading Page `OKTA_DEFAULT` |
| THEME-POS-010 | ✅ PASS | Email Template variant changed `OKTA_DEFAULT` → `FULL_THEME`. All other properties retained: Primary `#ff0000`, Secondary `#0000ff`, Sign-In `BACKGROUND_IMAGE`, Dashboard `FULL_THEME`, Error Page `OKTA_DEFAULT`, Loading Page `OKTA_DEFAULT` |
| THEME-POS-011 | ✅ PASS | Logo deleted successfully; theme reverts to default Okta logo. Confirmation prompt presented before deletion |
| THEME-POS-012 | ✅ PASS | Favicon deleted successfully; theme reverts to default Okta favicon. Confirmation prompt presented before deletion |
| THEME-POS-013 | ✅ PASS | Background image deleted successfully; theme reverts to default appearance. Confirmation prompt presented before deletion |

## 3.1.5 Custom Email Templates - Positive Scenarios

| Test ID | Result | Evidence |
|---|---|---|
| TEMPLATE-POS-001 | ❌ FAIL | `list_email_templates` → SDK deserialization bug: `execute()` receives single `EmailTemplateResponse` instead of `List[EmailTemplateResponse]`; templates returns `None`; `len(None)` raises `TypeError`; except block returns `dict` instead of `list`, causing Pydantic validation error |
| TEMPLATE-POS-002 | ❌ FAIL | `get_email_template` returns `{}` — SDK `execute()` deserializes to `None` when response body doesn't match expected type; `_serialize(None)` → `{}`. Same root cause as TEMPLATE-POS-001 |
| TEMPLATE-POS-003 | ❌ FAIL | `list_email_customizations` returns `{'error': "object of type 'NoneType' has no len()"}` instead of a list → Pydantic validation error `list_type`. SDK `execute()` → `None`; `len(None)` raises `TypeError`; except block returns `dict` instead of `list` |
| TEMPLATE-POS-004 | ❌ FAIL | `get_email_customization` returns `{}` — placeholder ID `id123` does not exist in org; SDK `execute()` → `None` for unmatched response types; `_serialize(None)` → `{}` |
| TEMPLATE-POS-005 | ❌ FAIL | `create_email_customization` → `{'error': "'NoneType' object has no attribute 'id'"}` — POST likely succeeded on Okta side but SDK `execute()` returns `None` on 200 response; tool then calls `.id` on `None`. Customization may exist in org |
| TEMPLATE-POS-006 | ❌ FAIL | `replace_email_customization` returns `{}` — ID `id123` does not exist; Okta returns 404; SDK deserializes error response to `None`; `_serialize(None)` → `{}`. No error key surfaced |
| TEMPLATE-POS-007 | ❌ FAIL | `replace_email_customization` (with `is_default=true`) returns `{}` — same root cause as TEMPLATE-POS-006: placeholder ID does not exist; SDK → `None`; `_serialize(None)` → `{}` |
| TEMPLATE-POS-008 | ❌ FAIL | `get_email_default_content` returns `{}` — `client.get_email_default_content()` deserializes to `None`; `_serialize(None)` → `{}`. No subject or body surfaced. Fix: direct `aiohttp` GET to `.../default-content` |
| TEMPLATE-POS-009 | ❌ FAIL | `get_email_customization_preview` returns `{}` — SDK `execute()` → `None` for preview response; `_serialize(None)` → `{}`. No rendered subject or body surfaced. Fix: direct `aiohttp` GET to `.../customizations/{id}/preview` |
| TEMPLATE-POS-010 | ❌ FAIL | `send_test_email` → `{'error': 'too many values to unpack (expected 2)'}` — SDK returns 3-tuple `(response, resp_body, error)` but tool unpacked only 2 values (`_, err =`). Fix: change to `_, _, err =` |
| TEMPLATE-POS-011 | ❌ FAIL | `get_email_settings` returns `{}` — SDK `execute()` → `None` for settings response; `_serialize(None)` → `{}`. No `recipients` value surfaced. Same root cause as TEMPLATE-POS-001/002/008/009 |
| TEMPLATE-POS-012 | ❌ FAIL | `replace_email_settings` returns `{}` — SDK `execute()` → `None` for PUT response; `_serialize(None)` → `{}`. No confirmation of updated `recipients` value. Same root cause as TEMPLATE-POS-011 |
| TEMPLATE-POS-013 | ✅ PASS | Email customization `id123` deleted successfully |
| TEMPLATE-POS-014 | ✅ PASS | All customizations for `ForgotPassword` deleted successfully; template reverts to Okta built-in default content |
| TEMPLATE-POS-015 | ❌ FAIL | `create_email_customization` → `{'error': "'NoneType' object has no attribute 'id'"}` — same root cause as TEMPLATE-POS-005: POST likely succeeded on Okta side; SDK `execute()` → `None`; tool calls `.id` on `None`. Body included `${activationLink}` and `${user.firstName}` |

## 3.1.6 Email Domains - Positive Scenarios

| Test ID | Result | Evidence |
|---|---|---|
| EMAIL-DOMAIN-POS-001 | ❌ FAIL | `list_email_domains` returns `total_fetched: 0`, `email_domains: []` despite domains existing in org (e.g. `agrajatest@aniketexample.com`). SDK deserializes API response to `None`; falls through to `domain_list or []`. Fix: direct `aiohttp` GET to `/api/v1/email-domains` |
| EMAIL-DOMAIN-POS-002 | ❌ FAIL | `list_email_domains(expand_brands=True)` same result as EMAIL-DOMAIN-POS-001 — empty list regardless of expand parameter. SDK → `None`; expand param has no effect. Fix: direct `aiohttp` GET to `/api/v1/email-domains?expand=brands` |
| EMAIL-DOMAIN-POS-003 | ❌ FAIL | `get_email_domain(edm123)` returns `{}` — SDK `execute()` → `None`; `_serialize(None)` → `None`. Placeholder ID `edm123` also does not exist in org. Fix: direct `aiohttp` GET to `/api/v1/email-domains/{emailDomainId}` |
| EMAIL-DOMAIN-POS-004 | ❌ FAIL | `create_email_domain` → `{'error': "'NoneType' object has no attribute 'get'"}` — POST likely succeeded on Okta side; SDK `execute()` → `None` on 200 response; tool calls `.get()` on `None`. Same root cause as TEMPLATE-POS-005/015 |
| EMAIL-DOMAIN-POS-005 | ❌ FAIL | `create_email_domain(validation_subdomain="mail")` — same SDK deserialization failure as EMAIL-DOMAIN-POS-004; `execute()` → `None` after POST; `.get()` on `None`. Subdomain parameter does not affect the failure |
| EMAIL-DOMAIN-POS-006 | ❌ FAIL | `get_email_domain(edm123)` returns `{}` — same root cause as EMAIL-DOMAIN-POS-003; `dnsValidationRecords` never surfaced. |
| EMAIL-DOMAIN-POS-007 | ❌ FAIL | `verify_email_domain(edm123)` returns `{}` — SDK `execute()` → `None` for POST `/verify` response; `_serialize(None)` → `{}`. No `validationStatus` surfaced. |
| EMAIL-DOMAIN-POS-008 | ❌ FAIL | `replace_email_domain(edm123)` raises Pydantic error: `"Input should be a valid dictionary [type=dict_type, input_value=None]"` — SDK `execute()` → `None` for PUT response; `_serialize(None)` → `None`; `Dict[str, Any]` return type validation fails. |
| EMAIL-DOMAIN-POS-009 | ✅ PASS | Email domain `edm123` deleted successfully (`success: true`). DELETE returns 204 No Content — no SDK deserialization involved |
