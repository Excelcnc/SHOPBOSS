# Excel SHOPBOSS

Excel CNC's quoting and shop-management app: RFQ inbox, part costing beside the drawing, quote
builder, Board, Jobs, Machines and Settings.

## Where it runs

SHOPBOSS runs as a claude.ai artifact:
**https://claude.ai/artifact/TrDjaGFKabt7vrpXDcp2eG**

`index.html` in this repository is the source of that artifact. The whole app is this one file. Your
data (RFQs, jobs, settings, mailbox links) is stored in the artifact's own database, not in this
repository, so this repository holds code only.

## Making changes

1. Change `index.html` here, on a branch, and open a pull request.
2. After merging, publish `index.html` to the artifact URL above (Claude does this with its Artifact
   tool, updating the same URL so links and data stay the same).
3. Before changing the code, compare it with the live artifact. If someone edited the artifact
   directly, bring those edits into `index.html` first so nothing is lost.

## How it reaches email

The page uses the signed-in user's Claude connectors (Microsoft 365 and Gmail) to read RFQ emails.
It never sends, moves or deletes mail.

Known limit: the Microsoft 365 connector returns the text it extracts from a PDF attachment, never
the file itself. That is why emailed drawings are listed by name but can't be previewed until they
are uploaded by hand. See `docs/EMAIL_FILES.md`.

## archive/

`archive/cnc-quote/` is an earlier, separate estimating app (FastAPI and React) kept for reference.
It is not SHOPBOSS and is not deployed.

Proprietary software of Excel CNC (see LICENSE).
