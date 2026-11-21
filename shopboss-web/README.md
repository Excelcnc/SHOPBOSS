# Excel SHOPBOSS web app

`index.html` is the Excel SHOPBOSS app (Board, Jobs, Machines, RFQ inbox, quote builder, Settings)
as it runs today on claude.ai. It is a single self-contained page: it keeps its data in the
artifact's database and reads mail through the signed-in user's Claude connectors.

Limit of this version: the Microsoft 365 connector returns only text extracted from a PDF, never the
file itself, so attachments collected from email cannot be previewed until they are uploaded by hand.
The backend in `../backend` fetches the real attachment bytes from Microsoft Graph and Gmail and
stores them the same way as uploads (see `../docs/EMAIL_FILES.md`).

The page holds demo data only. Live RFQs stay in the artifact database and are not in this repo.
