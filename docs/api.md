# API usage

All resource APIs use `/api/v1/`, session authentication and organization/project isolation. Start with `GET /api/v1/auth/session/`, save cookies and read `csrfToken`. Include `X-CSRFToken` and cookies on POST, PATCH and DELETE, including unauthenticated registration/login/reset requests. After login, use the newly returned CSRF token because Django rotates it. Resource list endpoints paginate at 30 records.

## Authentication

| Method and path | Input |
| --- | --- |
| GET `auth/session/` | Returns CSRF token and current user or null |
| POST `auth/register/` | `email`, `full_name`, `password1`, `password2` |
| POST `auth/verify/` | `token` from verification email |
| POST `auth/resend/` | `email` |
| POST `auth/login/` | `email`, `password` |
| POST `auth/logout/` | Empty body |
| POST `auth/password-reset/` | `email` |
| POST `auth/password-reset-confirm/` | `uid`, `token`, `password1`, `password2` |
| GET/PATCH `users/me/` | Editable: `full_name`, `company`, `contact` |

Passwords require at least 12 characters and Django's common-password, numeric and similarity checks. Verification expires after 24 hours; reset links expire after one hour and cannot be reused after changing the password. Avatar upload is currently provided by the HTML profile form.

## Organizations and projects

| Method and path | Behavior |
| --- | --- |
| GET/POST `organizations/` | List visible organizations or create one with an admin membership |
| GET/PATCH `organizations/{id}/` | Read or admin-only name/description updates |
| GET/POST/DELETE `organizations/{id}/members/` | List or administer membership using `email` and `role` |
| GET/POST `projects/` | List visible projects or create with `name`, `description`, optional `organization`, `target` |
| GET/PATCH `projects/{id}/` | Read or edit name/description/target; ownership and organization are immutable |
| POST `projects/{id}/archive/` | Admin/owner only; JSON `{"archived": true}` or false |
| GET/POST `projects/{id}/files/` | List files or multipart upload with `file` field |
| GET `files/{id}/download/` | Authorized attachment download |
| POST `projects/{id}/build/` | Queue `linear-int8-v1` with entrypoint; HTTP 202. Invalid input 400; unsupported pipeline 503. |

Organization deletion is disabled. Permanent project deletion is restricted to the super-admin interface with its confirmation page. Archive projects for normal lifecycle management.

## Compiler records

`GET builds/`, `builds/{id}/`, `builds/{id}/logs/`, `builds/{id}/stages/`, `artifacts/` and `artifacts/{id}/download/` provide scoped history and evidence. IR, RTL and verification records have read-only `/ir/`, `/rtl/` and `/verification/` routes. `/fabulous/targets/` lists global hardware profiles; `/x2/configurations/` lists only configurations in accessible projects.

`GET compiler/` returns stage status, execution configuration and the latest real tool probes. Recognized pipeline requests are routed through validated build services; unimplemented direct stage operations return HTTP 501 with `status: unsupported`. Configuration records can be managed by super administrators. Never expose arbitrary result creation to end users. See the README for current pipeline identifiers and their scope.

## Response conventions

- 200/201: read or real data mutation completed.
- 400: invalid form, metadata, membership role, file or reset/verification token.
- 403: unauthenticated session access, CSRF failure or insufficient role.
- 404: record missing or outside the caller's visible scope.
- 405: unsupported action such as destructive API deletion or GET logout.
- 429: request throttled.
- 501: compiler operation has no implementation.
- 503: build request recorded but compiler execution unavailable.

The checked-in `schema.yaml` is generated from the API. Regenerate after changing routes or serializers. The dashboard's API explorer makes real authenticated read requests and renders JSON as text.

See the [README](../README.md) for the input schema, configured worker and current artifact contract, and [architecture](architecture.md) for execution boundaries.
