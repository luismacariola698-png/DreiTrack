# DreiTrack v0.4 Migration Summary

Version 0.4 extends the v0.3 private single-company build to approved computers on the same private company LAN.

## Added

- `app/network.py` private-network helpers
- Private/public numeric source-IP classification
- Baseline same-origin protection for unsafe browser requests
- Per-installation generated session signing secret fallback
- Administrator network information in Company Settings
- `Enable Private Network Access.bat/.ps1`
- `Disable Private Network Access.bat/.ps1`
- `Show Private Network Address.bat`
- `network_info.py`
- Launcher `logs/network-info.txt`
- Private-LAN deployment documentation

## Private LAN activation

The default remains safe/local:

```text
127.0.0.1:8000
```

Running `Enable Private Network Access.bat` changes the launcher bind to:

```text
0.0.0.0:8000
```

and creates a Windows Firewall rule restricted to:

```text
Profile: Private
RemoteAddress: LocalSubnet
Protocol: TCP
Port: configured DreiTrack port
```

The firewall helper requires Windows administrator permission.

## Private LAN deactivation

Running `Disable Private Network Access.bat` removes the firewall rule and restores `127.0.0.1`.

## Session secret change

v0.3 could use a shared development fallback when `DREITRACK_SESSION_SECRET` was unset.

v0.4 instead generates a random secret once per installation and stores it in `.dreitrack_session_secret`. The file is Git-ignored.

## Security scope

This version is designed for a trusted private office/company LAN. It is not intended for direct public-internet exposure.

Plain HTTP is still used by default, so private HTTPS/VPN access remains part of the next hardening phase.
