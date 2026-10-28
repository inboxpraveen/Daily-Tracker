# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private reporting: open the repository's **Security** tab and choose **Report a vulnerability**. You can also email the maintainer; the address is on the GitHub profile of the repository owner.

Include a description, steps to reproduce and the affected version. You will get an acknowledgement within a few days. Fixes go out as a new release and are credited in the changelog unless you would rather not be named.

## What HabitFlow protects, and what it leaves to you

HabitFlow is a single-user app that runs on your own computer. It is built so that nothing about it is reachable from outside that computer:

- **Local only.** The server binds to `127.0.0.1`. It is not reachable from other machines.
- **Host check.** Any request whose `Host` header is not `127.0.0.1`, `localhost` or `::1` gets a `403`. This stops DNS rebinding, where a hostile web page points its own domain at `127.0.0.1` to talk to local services.
- **No third parties.** The app makes no outbound requests, and no page loads a font, script or stylesheet from another host. There is no analytics and no update check.
- **No CORS.** The server sends no cross-origin headers, so other websites cannot read its responses, and JSON writes from other websites are blocked by the browser's preflight. The one body-less state change, restoring a removed habit, can only reactivate a habit you had removed.
- **Your data is a file.** Habits and ticks are in one SQLite file in your user profile, protected by your operating system's normal file permissions. It is not encrypted at rest. Use full-disk encryption if that matters to you.
- **Debug mode is off.** Flask's debugger, which can run code, only starts when you set `HABITFLOW_DEBUG=1` for development.
- **Untrusted input.** Request values are SQL bound parameters, and colours, dates and ids are validated before they are stored. A restore file is checked before any data is deleted.

There are no user accounts, no login, no rate limiting and no audit trail, because a single-user local app does not need them. **Do not expose HabitFlow's port to a network** (a port forward, a tunnel, `0.0.0.0`) without putting your own authentication in front of it.

## The installer

The Windows installer and the exe are **not code-signed**, so Windows SmartScreen shows a warning. Every release is built on GitHub Actions from the tagged source, and the build log is public in the Actions tab. You can build the installer yourself, see [the README](README.md#building-the-installer-yourself). Verify what you downloaded against a build from source if you need to be sure.

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release | yes |
| Anything older | no. Install the latest release |
