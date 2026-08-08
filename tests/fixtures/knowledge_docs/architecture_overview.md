# Engineering Architecture Overview

Alderbrook Systems' product is built as a set of services in a monorepo, deployed via Buildkite
CI/CD to AWS. Core services: `api-gateway` (routes external requests), `billing-service`,
`notifications-service`, and `search-service` (backed by OpenSearch).

Data is stored in a primary PostgreSQL instance (`prod-primary`) with read replicas for reporting
queries. Internal services communicate over gRPC; external APIs are REST.

New services must register with the internal service catalog and pass a security review before
being granted production access. See the runbooks for deployment and incident procedures.
