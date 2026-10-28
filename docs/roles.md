# Roles and Access

How a user's role is stored, what each role may do, and how to grant one.

---

## Where the role lives

A user's role is stored in Supabase Auth, in `auth.users` under `app_metadata.role` (the `raw_app_meta_data` column). Only the service role can write it. `user_metadata` is writable by the user, so a role must never be read from there.

No role means a regular member (a "customer"). The backend reads the role from Supabase on every request, so a change takes effect on the next call and does not wait for a token to expire.

Login, the OAuth session exchange and refresh all return `{ access_token, role }`, so the frontend learns the role without needing a profile. `role` is `null` for a customer.

---

## Known roles

| Role | Profile | Can do |
|---|---|---|
| none (customer) | yes | Everything a member can, once the T&C and Privacy Policy are accepted |
| `admin` | no | Browse community, event and profile content read-only, and use the admin tools |

`KNOWN_ROLES` and `GHOST_ROLES` in `app/common/config/constants.py` define which roles the backend recognizes and which of them browse without a profile (a "ghost"). A ghost cannot create a profile, chat, connect, post or react, and cannot open the chat WebSocket.

An unrecognized role value is refused with a 403 on every API call, on login, on the OAuth session exchange and on refresh, and the WebSocket is closed. The account is locked out until the value is fixed, which is deliberate: a typo must never grant access. Logout still works.

---

## Access levels in the code

Every route chooses one of these dependencies from `app/common/dependencies/auth.py`:

| Dependency | Who gets in |
|---|---|
| `get_consented_customer` | Customers who have accepted the T&C. The default for member routes. Ghosts are refused. |
| `get_viewer` | Customers who have accepted the T&C, and ghosts. For read-only routes only. |
| `get_customer` | Customers, whether or not they have accepted yet. For routes that run before consent exists: profile creation, `/users/me`, accepting the legal documents. Ghosts are refused. |
| `get_current_user` | Any signed-in account, whatever its role. Used by `GET /interests`, which the profile-setup form needs before consent. |
| `get_admin` | The `admin` role only. All of `/api/admin/*`. |

A new route should use `get_consented_customer` unless there is a reason not to. A route is open to ghosts only if it uses `get_viewer`, and `tests/test_route_access.py` fails until the route is listed there, so the decision is always a deliberate one.

---

## Creating a privileged user

Privileged accounts are never self-service. Anyone who signs up, by email or with Google, is a customer.

1. In the Supabase dashboard, go to Authentication, Users, Add user, and tick **Auto Confirm User**.
2. In the SQL editor, check the row, then merge the role into `app_metadata`:

```sql
select id, email, raw_app_meta_data from auth.users where email = 'admin@example.com';

update auth.users
set raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb) || '{"role": "admin"}'::jsonb
where email = 'admin@example.com';
```

Use `||` to merge. The column also holds `provider` and `providers`, and overwriting it breaks sign-in.

If the person signs in with Google using the same verified email, they land on the same account, so the role applies there too.

### Adding a new role

Add it to `KNOWN_ROLES` in `constants.py` first, and to `GHOST_ROLES` too if it should browse without a profile. Only then assign it in the database. A user given a role the backend does not know yet is locked out until the code ships.

---

## Moderator actions and profiles

An admin has an `auth.users` row but no `public.users` row. The columns that record who made a moderation decision (`actioned_by`, `created_by` and `lifted_by` on `moderation_reports`, `user_reports`, `moderation_filtered_messages` and `moderation_bans`) therefore reference `auth.users`, not `public.users`. Keep that when adding a new column that stores an admin's id.
