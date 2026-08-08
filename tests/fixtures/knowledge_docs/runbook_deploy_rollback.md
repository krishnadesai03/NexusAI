# Runbook: Rolling Back a Bad Deployment

If a deployment causes elevated error rates (check the #alerts-prod Slack channel or the Grafana
dashboard "prod-error-rate"), follow these steps:

1. Confirm the regression started at the deploy timestamp by checking the deploy log in
   Buildkite.
2. Run `deploy-tool rollback <service-name>`, which redeploys the previous known-good image tag.
3. Rollback typically completes within 5 minutes; verify error rate returns to baseline on the
   Grafana dashboard.
4. Post an incident summary in #eng-incidents including root cause if known.
5. If rollback doesn't resolve the issue within 10 minutes, escalate to the on-call lead per the
   incident runbook.
