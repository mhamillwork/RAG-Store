# Security

Authorization is enforced in the file and search services and again by PostgreSQL policies. The GUI hiding an admin button is not the control.

Path checks reject `..`, absolute paths, and symlinks that escape a root. Uploaded source is never executed.

Containers run as uid 10001, except the unprivileged nginx image which uses uid 101. Capabilities are dropped. The service account does not mount a Kubernetes token. NetworkPolicy is off until CIDRs are set; an enabled policy with no egress CIDRs denies egress.

Trusted administrators with database or PVC access are outside this boundary. That access is not granted by the application.

The integration test checked that a second user cannot read or find another user's LOCAL document. It did not include a penetration test.
