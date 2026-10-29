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
files return 404. **Review in PDF** opens a dedicated WebUI tab. It loads the
original through the authenticated endpoint, displays the graph assertion and
grounded quote alongside the PDF, and highlights a unique verbatim PDF.js text
match. No original PDF bytes are modified. The viewer searches the page anchors
saved with the source chunk first. `POST /documents/{doc_id}/source-pdf/locate`
is the fallback when an older chunk has no saved anchor; repeated matches are
reported as ambiguous rather than silently selecting one. Figures, formulas,
OCR differences and large PDF text runs may prevent a precise mark. Reviewers
must still inspect the original page and assess whether the marked text supports
the **relation**, not just whether the words appear.

For new Legacy PDF ingestion, `full_docs.source_page_ranges` preserves page
offsets after the PDF text is sanitized. For Docling/MinerU PDFs, the existing
`blocks.jsonl` positions provide page ranges. A chunk receives a
`pdf_location` only if its text has a unique normalized match in the parsed
document. The exact relation quote (`evidence_quote`) is passed to review
sources when extraction grounded it in that chunk.

To test persisted anchors, ingest or fully re-parse a PDF **after** deploying
the backend change, then create a **new** Human Review session and click
**Review in PDF** beside a hop with a source. The graph-only `/documents/reextract`
operation retains old chunks and does not add page anchors; the viewer can
still use its slower page-search fallback for those documents. Confirm the
sidebar shows the expected relation and quote, and that the yellow mark is on
the right page. A missing mark is preferable to marking an unrelated passage.

MCP citations and exploratory sources include a separate `pdf_url` when
`LIGHTRAG_PUBLIC_WEBUI_BASE_URL` is set on the MCP gateway to the HTTPS WebUI
origin (provided for Staging by `deploy/mcp/compose.staging-source-links.yml`). External publisher
URLs remain unchanged. Opening the protected PDF link in a browser still
requires a WebUI OAuth login; it does not make private PDFs public to ChatGPT.
