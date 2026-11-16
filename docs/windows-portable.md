# Private all-in-one Windows deployment

The generic single-file build now includes:

- Flet/Python desktop and web runtimes, fonts, logos and factory map.
- The SQLite/HTTP bridge and monitoring/battery policy workers.
- Windows Mosquitto broker and publisher/subscriber, dependent DLLs and licenses.
- Windows cloudflared executable and license.
- ESP32-S3 firmware, flash manifest, esptool, mklittlefs and their DLL/licenses.
- Windows-compatible UDP discovery and network adapter enumeration.

Launching the Windows executable starts the local broker, bridge and web origin
before the desktop window. `--web` runs the same services without a desktop
window. Source/Linux runs retain their existing launch behavior. Services started
by this app are stopped when the app exits; other running services are reused.

Mutable data lives under `%LOCALAPPDATA%\Roztash`, not the temporary onefile
extraction directory. `ROZTASH_HOME` can override this location. Settings, logs,
photos and SQLite updates persist across launches and executable upgrades.

## Owner-only personalization

After downloading the generic executable, run **locally**:

```bash
.venv/bin/python scripts/personalize_windows_exe.py BASE.exe PRIVATE.exe
```

This appends a strictly allowlisted private first-run payload containing the
current SMTP configuration, Cloudflare settings and credentials, admin roles,
emergency key if configured, SQLite online backup and employee photos. It never
copies an authenticated desktop session, bridge signing key, logs, Linux
binaries, caches or process IDs. The Windows host creates its own bridge key.
Existing destination state is never overwritten by the first-run importer.

The private executable contains extractable credentials and health records.
It is not encrypted. Keep it owner-only; never upload it or the attached data
to GitHub, a public release or CI. Generic CI artifacts contain no private data.

## Remaining environmental requirements

- The destination needs supported Windows x64 and network access to mail and
  Cloudflare services. Packaging credentials does not prove SMTP authentication
  or mail delivery. No live credential test is performed in GitHub Actions.
- Gateways require a functioning LAN and DHCP provider such as a router; an
  unmanaged switch does not provide DHCP. Do not start another DHCP server
  automatically on an existing network.
- Allow the application/broker through Windows Firewall only on the trusted
  private LAN. USB serial drivers may be required for the physical board.
- Cloudflare uses the same named tunnel. Do not leave the old Linux origin
  attached after the Windows host takes over: traffic can otherwise reach either
  independent database. Stop the old host when completing the migration.
- UI attendance/report areas still marked as prototype retain that behavior;
  portability does not implement unfinished product features.

To prioritize delivery at the owner's request, `run_checks=false` can skip CI
regressions and launch tests. Archive/payload integrity inspection still runs.
A build made this way is delivered for the owner's actual Windows test, not
reported as fully runtime-tested.
