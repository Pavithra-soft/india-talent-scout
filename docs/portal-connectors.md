# Portal connectors

Talent Scout searches only through adapters. It does not log in to a job portal, store a portal password, or crawl a site.

Each adapter implements:

- `enabled()` — whether this recruiter may use it
- `quota_remaining()` — a number when the portal reports one, otherwise nothing
- `search(plan)` — profiles for an approved search plan
- `fetch_profile(portal_id)` — one profile
- `download(profile)` — a filename and file bytes the browser can save

Register the class in `available_connectors()` in `app/portal_connectors.py`, and add its key to the connector list on the portal search page.

## Ways to add a portal

1. **Licensed API.** Set a base URL and API key on the portal search page, or set `PORTAL_API_BASE` and `PORTAL_API_KEY`. The key is encrypted with the app secret. The API must accept `GET {base}/v1/profiles?q=` with `Authorization: Bearer` and return JSON:

   ```json
   {"quota_remaining": 10, "profiles": [{"id": "1", "name": "", "email": "", "skills": "", "location": ""}]}
   ```

2. **Browser extension.** Load `extension/` in Chrome or Edge as an unpacked extension. Open a portal page you are already logged into, open the extension, and send the rows you tick. The extension permission is `activeTab` only. It does not request cookies.

3. **CSV.** Export from the portal’s own export button and import that file on the portal search page.

The mock connector is always available and uses the sample people in `MockPortalConnector`. Use it for demos and tests.

## Assumptions

- One recruiter password is the tenant. Plans, hits, and the API key are tied to that session and expire with the JD workspace (`JD_TTL_HOURS`).
- Ranking uses the same scorer as local resumes, including when a portal only returned a short snippet.
- Duplicate people are collapsed by email, phone, or the same name plus company.
- Downloaded files are written by the browser. The server keeps the structured fields only until the workspace expires or is cleared.
- A licensed API speaks the JSON shape above. Partner-specific OAuth for LinkedIn, Naukri, or Indeed is not wired until that vendor grants access.

## Open questions

- Which licensed APIs will actually be contracted, and what quota headers they return.
- Whether the browser extension should ship in the Chrome Web Store or stay unpacked for the recruiting team.
- How long the audit log of searches and downloads should be kept after the workspace itself is deleted. Today the audit rows are not tied to the 24-hour workspace purge.
- Whether “find similar” should call every enabled connector or only the mock portal. It currently searches the mock portal.
