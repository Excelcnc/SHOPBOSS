# Emailed drawings in SHOPBOSS

## What happens today

1. SHOPBOSS finds RFQ emails through the Microsoft 365 connector (`outlook_email_search`, `read_resource`).
2. For each attachment it saves the name, size and the attachment's `mail:///` link. The file is
   marked `ref: "missing"`.
3. For PDFs it asks the connector to read the attachment. The connector returns **text extracted from
   the PDF**, or a note such as "PDF text extraction failed", but never the file bytes.
4. Preview (pdf.js) and drawing reading need the real file, so the file stays "In the email:
   download, then drop here".

This was checked against the live mailbox on 2026-11-21: reading the attachment
`A3-0511-01 RFQ-20261118-002 Drawing.pdf` returned only a "text extraction failed" note.

## Why the page can't simply download the file

An artifact page can reach email only through the claude.ai connectors it declares. None of the
Microsoft 365 connector's tools return attachment bytes. The Gmail connector has
`download_gmail_attachment`, which does return the file, but SHOPBOSS's mailboxes are Outlook.

## Ways to get real files without download and re-upload

- **A. A Gmail inbox for RFQs.** Forward RFQ mail to a Gmail or Google Workspace inbox connected to
  Claude. SHOPBOSS could then fetch each attachment with `download_gmail_attachment` and store it the
  same way as a manual upload (artifact file storage), then run the same preview and analysis.
  Not yet tested: the Gmail connector currently returns an account error for this login, so whether
  the artifact receives the bytes still has to be confirmed with a working Gmail connection.
- **B. A small server.** A server with read-only Microsoft Graph access (`Mail.Read`) can download
  attachment bytes. The page can only reach it if the artifact platform allows it to call that
  server.
- **C. Keep the current workaround.** Drag the attachment from Outlook onto the RFQ.
