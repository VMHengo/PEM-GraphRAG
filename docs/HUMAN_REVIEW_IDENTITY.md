# Human Review Identity

The Human Review tab pre-fills the reviewer name from the authenticated OAuth2
Proxy session. The four current reviewer emails have friendly-name defaults in
`lightrag/evaluation/reviewer_identity.py`. A user can edit the displayed name;
that preference is stored in browser localStorage separately for each email.

On every review save, LightRAG calls OAuth2 Proxy's `/oauth2/userinfo` with the
incoming session cookie. It stores both `reviewer` (editable name) and
`reviewer_email` (verified email) in the immutable review event. Neither a
browser-supplied email nor `X-Forwarded-Email` is accepted as proof of identity.
Older review events without `reviewer_email` remain readable.

The LightRAG container must reach OAuth2 Proxy at
`http://oauth2-proxy:4180` (the default). Set `REVIEW_OAUTH2_PROXY_URL` in the
LightRAG service environment if its internal service name differs. The WebUI
must be accessed through OAuth2 Proxy; direct API-key access cannot create
verified human reviews. If the proxy is unavailable or the session lacks an
email, saving fails closed. Do not expose LightRAG's internal port publicly.

After deployment, sign in to the WebUI as each reviewer and open Human Review.
Confirm that the expected friendly name and email appear. Save a test review,
then verify the returned review JSON contains the chosen `reviewer` and the
logged-in `reviewer_email`. Do not paste session cookies or tokens into logs.

## Original PDFs in Human Review

Human Review links each PDF source to `GET /documents/{doc_id}/source-pdf`.
This endpoint uses the same server-verified OAuth2 Proxy session as reviewer
identity and serves only a uniquely matched retained original under the
workspace input directory or its `__parsed__` archive. It does not accept a
filesystem path or grant access by API key alone. Removed or ambiguous original
files return 404. The WebUI PDF button opens the original in a protected viewer;
`POST /documents/{doc_id}/source-pdf/locate` searches extracted PDF text for
the review excerpt and opens a matching page when found. The excerpt remains
visible beside the original for comparison. This is a page locator, **not** a
coordinate-accurate PDF highlight: figures, formulas and OCR differences may
prevent an exact text match. Reviewers must inspect the original page.

MCP citations and exploratory sources include a separate `pdf_url` when
`LIGHTRAG_PUBLIC_WEBUI_BASE_URL` is set on the MCP gateway to the HTTPS WebUI
origin (provided for Staging by `deploy/mcp/compose.staging-source-links.yml`). External publisher
URLs remain unchanged. Opening the protected PDF link in a browser still
requires a WebUI OAuth login; it does not make private PDFs public to ChatGPT.
