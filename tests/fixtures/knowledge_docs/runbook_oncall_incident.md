# Runbook: On-Call Incident Response

When PagerDuty triggers an alert:

1. Acknowledge within 5 minutes to avoid auto-escalation.
2. Join the #incident-response Slack channel and post "investigating [alert name]".
3. Assess severity: Sev1 (full outage) requires immediately paging the on-call lead and opening a
   Zoom bridge; Sev2/Sev3 can be handled solo with status updates every 30 minutes.
4. Once resolved, post a resolution summary and schedule a blameless postmortem within 3 business
   days for any Sev1/Sev2 incident.
5. Update the incident tracker in Jira with timeline and root cause.
