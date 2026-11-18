# Roadmap

## Next (to put Excel CNC into daily use)
2. Connect the quoting mailbox in your tenant; deploy to Azure Container Apps
   (PostgreSQL Flexible Server, Azure Cache for Redis, Blob storage) with a public HTTPS URL for the Graph webhook.
3. Calibrate with your JobBOSS² history (docs/ESTIMATING.md) and tune per-feature times.
4. Alembic migrations; nightly database backups.
5. Edit volume-discount tiers and quote PDF branding (logo, terms) in Shop settings.

## Then
- JobBOSS² integration: push accepted quotes as quotes/jobs; pull history automatically
  (depends on your JobBOSS² edition's API access — CSV import works today).
- Thread recognition from STEP AP242 PMI and cosmetic threads; rib and chamfer naming.
- OCR fallback for scanned drawings without AI.
- DWG via a server-side converter.
- GitHub sign-in for shops without Microsoft 365, and self-service shop onboarding.
- pgvector for similarity at large history volumes.

## Later (v2)
- Mastercam add-in to pull CAM cycle times back into estimates (requires a licensed workstation).
- Offline mode.
- Customer portal for RFQ submission and quote acceptance.
- Learn per-shop coefficients from won/lost and actual hours.
