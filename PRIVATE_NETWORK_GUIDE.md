# DreiTrack Private Network Guide

This guide explains the v0.4 office-LAN deployment in plain language.

## Which computer runs DreiTrack?

Choose one Windows computer that stays on while employees need the system. That computer is the **DreiTrack server**.

It stores the application/database and runs Ollama/Drei.

Other employees do not install DreiTrack. They only open it in a browser.

## Server setup

1. Run `Setup DreiTrack.bat` once.
2. Build the local Ollama model if it is not already installed.
3. Run `Enable Private Network Access.bat` once and approve the Windows administrator prompt.
4. Start DreiTrack with `DreiTrack.vbs`.
5. Optionally run `Enable Auto Start.vbs` so the server starts automatically when the Windows account signs in.

## Finding the address

On the server computer, either:

- open Company Settings and look at **Private Network -> Company Network Access**, or
- run `Show Private Network Address.bat`.

Employees can usually use:

```text
http://SERVER-COMPUTER-NAME:8000
```

If that name does not resolve, use the private IPv4 address shown by DreiTrack, for example:

```text
http://192.168.1.25:8000
```

## Employee computers

Employee computers only need:

- access to the same private company LAN;
- a web browser;
- a DreiTrack account created by the administrator.

They do not need Python or Ollama.

## Windows Firewall design

The enable helper creates one inbound rule:

```text
Name: DreiTrack Private LAN
Direction: Inbound
Action: Allow
Protocol: TCP
Port: 8000 by default
Profile: Private only
Remote address: LocalSubnet only
```

This is intentionally narrower than an "allow from anywhere" firewall rule.

## Do not use guest/public Wi-Fi

A company guest Wi-Fi or public hotspot should not be used as the trusted DreiTrack LAN.

The Windows network profile on the server should be **Private** only when that network is genuinely trusted and controlled by the company.

## Do not port-forward DreiTrack

Do not forward TCP port 8000 from the public internet router to the DreiTrack server.

For remote employees, add a private VPN or private overlay network in the next deployment phase.

## Current HTTP limitation

The default v0.4 LAN URL uses `http://`, not HTTPS.

This keeps setup simple for a controlled office network, but traffic is not encrypted in transit. For sensitive production use, the next step is private HTTPS/VPN access.

## Stopping or disabling access

- `Stop DreiTrack.vbs` stops the web server.
- `Disable Private Network Access.bat` removes the firewall rule and returns the launcher to local-only `127.0.0.1` mode.

## Drei architecture

Drei runs only on the server computer:

```text
Employee browser
      |
      v
DreiTrack server
      |
      +--> organization-scoped inventory database
      |
      +--> deterministic planning/anomaly logic
      |
      +--> local Ollama / Drei
```

Employees do not receive direct access to Ollama. They interact with Drei through authenticated DreiTrack pages.
