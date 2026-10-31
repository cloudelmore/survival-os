# Security policy

SURVIVAL OS is pre-release, so only the latest commit on `main` is supported.

Please report vulnerabilities privately through GitHub security advisories, not public issues.

Default posture:

- Services listen on loopback only. LAN sharing is off until the user enables it.
- SSH is disabled in release images unless the user enables it.
- No credentials are embedded in images or stored in Git.
