# Stable releases

The native update worker accepts annotated, GPG-signed semantic version tags from the fixed official repository. Ordinary branch commits are not automatic update candidates.

1. Run backend, native engine, frontend and database compatibility checks.
2. Set `VERSION`, backend version and frontend package version to the same stable version.
3. Commit the release and sign `vMAJOR.MINOR.PATCH` with the release key corresponding to `deploy/releases.pub`.
4. Verify the tag in a separate GPG home containing only that public key, then push the commit and tag.

Keep an encrypted offline backup of the private signing key, its revocation certificate and recovery instructions. The private key must never enter Git, an application image, the web server or an installed panel. Key loss prevents signing compatible future updates; a replacement trust key must be distributed through an existing trusted signed release or manually installed by the operator. Rotate expiring keys before expiry.

Updater checks build candidates before stopping services, require an encrypted pre-update backup and preserve deployment environment/data. Failed installation attempts code and binary rollback; database downgrade is not automatic. Release migrations must remain compatible with the prior application until operators have verified the update. A clean-server installation and full upgrade/recovery rehearsal remain separate deployment gates.
