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
