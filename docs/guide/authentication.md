# Authentication

opengwaspy needs to know where the API is, and who you are.

## Settings

Each setting is taken from, in order: the arguments you pass, the environment, your config file, and the defaults.

| Setting | Argument | Environment | Config file |
|---|---|---|---|
| API URL | `url=` | `OPENGWAS_URL` | `url` |
| Named URL | `profile=` | `OPENGWAS_PROFILE` | `profile` |
| Data API developer key | `token=` | `OPENGWAS_TOKEN` | `token` |
| OpenGWAS token (for the Gateway) | `jwt=` | `OPENGWAS_JWT` | `jwt` |

```python
import opengwaspy as og

og.configure(url="https://...", token="...")      # the default client
client = og.Client(url="https://...", token="...")  # or a client of your own
og.tophits("OGS-00006:GCST90199621", client=client)
```

**The config file** is TOML, at `~/.config/opengwaspy/config.toml` on Linux (`$OPENGWAS_CONFIG` overrides the path):

```toml
url = "https://..."
token = "..."
```

Keep it private (`chmod 600`); opengwaspy warns if others can read a file that holds a key. A project's `.env` file is never read by opengwaspy itself.

Keys never appear in `repr`, logs or error messages.

## Now: developer keys

While the Data API is in development, you call it directly with a **developer key** issued by its operators. Each key has its own share of the queue: a few jobs at a time.

## Next: the Gateway

In production, OpenGWAS is reached through the **Gateway** (`https://api.opengwas.io/ogdb`, `profile="gateway"`). The Gateway authenticates you, applies your allowance, and passes your queries to the Data API.

- **Today** the Gateway takes an OpenGWAS token (a JWT) from your [OpenGWAS profile](https://api.opengwas.io/profile/). Set it as `OPENGWAS_JWT`. Tokens last 14 days, and getting a new one revokes the old.
- **The Gateway's sign-in flow is not final.** opengwaspy handles authentication through providers (`DeveloperKey`, `OpenGWASToken`, and a future sign-in provider), so your code will not need to change when it is. See the [project board](https://github.com/orgs/opengwas/projects/1) (Python client).

When your Gateway allowance runs out, opengwaspy waits for it to reset if that is soon. Otherwise it raises `RateLimitError` saying when it resets.
