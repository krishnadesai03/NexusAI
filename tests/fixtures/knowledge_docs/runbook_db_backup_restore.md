# Runbook: Database Backup & Restore

Production databases are backed up automatically every 6 hours via automated snapshot, retained
for 14 days.

To restore from a snapshot:

1. Identify the target snapshot timestamp in the AWS RDS console under the `prod-primary`
   instance.
2. Request approval from the on-call DBA lead before restoring, since this creates a new instance
   rather than overwriting the original (to avoid data loss).
3. Run `db-restore-tool --snapshot <id> --target staging-restore-check` to validate integrity in
   staging first.
4. Only promote to production after validation and a second engineer's sign-off.

Full restore typically takes 20-40 minutes depending on database size.
