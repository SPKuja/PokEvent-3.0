# Claiming a League (PokEvent 3.0)

PokEvent discovers official tournaments through Pokédata, which can have stale
details after cancellations or time/venue changes. To allow safe manual
corrections, **one Discord server can own one Pokémon League**, and a League
can be verified to **only one Discord server**. Following or configuring
another League does not grant editing rights.

## Configure the PokEvent owner

In your Portainer stack, pass your **numeric Discord user ID** to the bot:

```yaml
x-pokevent-environment: &pokevent-environment
  POKEVENT_OWNER_USER_ID: ${POKEVENT_OWNER_USER_ID:-}
```

Then set `POKEVENT_OWNER_USER_ID` in the Portainer stack's environment
variables. The existing Discord token and other settings must remain intact.
If the variable is absent, no owner invitations are sent and claim reviews
are disabled; existing event syncing/announcements continue normally.

You can get your Discord ID by enabling **Developer Mode** in Discord settings,
right-clicking your profile, and choosing **Copy User ID**.

## Existing servers

After the new bot container starts, it sends **one DM** to each existing
Discord server owner **if that server has configured a default League**.
The DM explains why event changes need to be maintained manually and asks
whether they own the default League.

- **Yes:** creates a pending claim and notifies the configured PokEvent owner
  by DM, with Approve and Reject buttons. It does not grant access yet.
- **No thanks:** remembers the decline; the server still receives all
  Pokédata event announcements and can view events, but nobody may edit them.
- **DMs disabled:** the server owner can always initiate the claim using
  `/pokevent claim` inside their server.

Owners can use `/pokevent claim` later if they change their mind.
The bot also offers a claim when a server's default League is first set.

## Review and manage claims

Only the configured `POKEVENT_OWNER_USER_ID` can approve or reject claims,
including via DM or these fallback commands in any server running the bot:

- `/pokevent claims` lists pending requests with the Guild ID, League ID
  and claiming owner.
- `/pokevent reviewclaim guild_id:<ID> approve:true` verifies a claim.
- `/pokevent reviewclaim guild_id:<ID> approve:false` rejects a claim.
- `/pokevent releaseclaim guild_id:<ID>` releases a server's claim.

**Verify ownership independently before approving.** A League ID can be
entered by any Discord admin as a subscription and is not evidence of
ownership. The bot also checks whether the server's current owner submitted
the request and whether the default League changed since the request.

A server owner can use `/pokevent unclaim` to relinquish an active claim.
A server that is not approved cannot edit even if it has configured the
League as its default.

The PostgreSQL database enforces uniqueness of approved League claims, so
two servers cannot simultaneously own the same League.

## Manual event corrections

Once approved, **all Discord administrators in the claimed server** can use:

- `/pokevent setup` → **Manage Events**, or
- `/pokevent manageevents`.

Choose one of the upcoming events from that *one verified League* and:
mark it cancelled, mark it active, correct its title/time/venue, or restore
Pokédata's original values. Time entry uses `YYYY-MM-DD HH:MM` in UK
local time. Cancelling updates affected Discord announcements, including
other servers that merely follow the League.

Every write checks the real event's stored League ID and the currently
approved server claim on the backend — **not** the event name, the selected
dropdown, or which other Leagues the server follows.

Corrections are stored in `manual_event_overrides`, which takes precedence
over Pokédata and the optional verification feed on every routine sync. A
manual status also prevents missing-event reconciliation from undoing it.
Removing the correction restores Pokédata on the next successful sync
(and tries to refresh immediately).

An append-only `event_edit_audit` records the Discord administrator,
server, League, original fields, changed fields and UTC timestamp of edits
and restorations.

All records live in Postgres; the migration is
`0013_league_claims.py`. The bot still works normally if no Leagues have
been claimed.
