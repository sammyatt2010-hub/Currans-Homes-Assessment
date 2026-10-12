# Currans Homes – Call Insights portal

A password-protected Streamlit portal that pulls call records **live from the Currans Homes Grandstream UCM**:
no exports, no uploads. Customers sign in and see the call handling dashboard, the user assessment and both
PDF reports, for this month, last month, the last 7 or 30 days, today, or a custom range.

It uses the same analysis and report code as the main Call Insights app (`cdr_engine.py`, `users.py`,
`report_pdf.py`, `ui.py`). When you improve the main app, copy those four files in here too.

## How it gets the data

`ucm_client.py` talks to the UCM's API:

1. **HTTPS API** (port 8089), using the API user created under *Integrations > API Configuration*:
   challenge → MD5 token → login cookie → `cdrapi` requests in pages of 1,000 calls.
2. If that fails, the **legacy CDR API** (`https://<ucm>:8443/cdrapi`, digest authentication).

Every call comes back with all its legs (`main_cdr` + `sub_cdr`), exactly like the CSV export, so the
figures match what the upload app produces. Data is cached for 10 minutes (`refresh_minutes`). **Refresh now**
in the sidebar pulls the latest calls immediately.

## Setup

### 1. On the UCM
1. *Integrations > API Configuration > HTTPS API Settings*: tick **Enable**.
2. **Create New API User**: pick a username (e.g. `callinsights`) and a long random password.
3. **Address Allowlist**: add the public IP address of whatever hosts this portal (see step 2).
   Failed logins can get an address blocked, and the allowlist stops the portal's own address being blocked.

### 2. Network – the UCM must be reachable by the portal
The portal runs on the internet, so it needs to reach the UCM's API port over the internet:
- On the Currans router, forward a TCP port to the UCM's port 8089. Ideally restrict it to the portal's IP
  at the firewall as well as in the allowlist.
- **Streamlit Community Cloud doesn't give apps a fixed outgoing IP address**, so you can't reliably allowlist
  it. Two options:
  - **Recommended:** host the portal somewhere with a static IP (a small cloud server or VPS running
    `streamlit run app.py`), and allowlist that one IP on the UCM and the router.
  - **Simpler but less locked-down:** run it on Streamlit Cloud with the allowlist left open, relying on a
    strong API password and the UCM's lock-out on failed logins. The API user can only read data, but this
    still exposes the PBX's API to the internet.

### 3. Deploy the portal
1. Push this folder to a **new private GitHub repo** (e.g. `currans-call-insights`).
2. Deploy it (Streamlit Cloud: *New app* → repo → `app.py`; or on your own server).
3. Paste the settings from `.streamlit/secrets.toml.example` into the app's **Secrets** and fill in:
   - `[portal_users]`: one line per person, `username = "password"`. Put yourself in `admins`.
   - `[ucm]`: the UCM's public address, port, API username and password.
   - `[report]`: Currans' opening hours/days (e.g. add `"Sat"` if they open Saturdays).
4. Sign in as your admin user, open **Admin · phone system connection** and click **Run connection test**.

The portal refuses to run if no users are configured, and repeated wrong passwords are slowed down.

## Admin tools (admin users only)
- Connection test: login → read today's calls, with plain-English errors.
- Shows which API route was used and how many calls the last pull fetched.
- Upload fallback: load a CDR export manually if the connection is down.

## Files

| File | Purpose |
|---|---|
| `app.py` | The portal: login, live data, period picker, admin tools |
| `ucm_client.py` | Grandstream UCM API client (HTTPS API + legacy CDR API) |
| `ui.py` | Shared dashboard, tabs and downloads (same as the main app) |
| `cdr_engine.py`, `users.py`, `report_pdf.py` | Shared analysis and PDF code (same as the main app) |
| `fonts/` | Inter font for the PDFs |
| `.streamlit/secrets.toml.example` | Settings template - copy into the app's Secrets |

## Tested
Against a simulated UCM serving the real Currans CDR data (29 Sep – 12 Oct 2026) through the documented API
(challenge/login/cookie, 1,000-call paging, digest auth on the legacy route). The figures matched the CSV upload
exactly. Not yet tested against the live UCM. Run the connection test first after setup.
