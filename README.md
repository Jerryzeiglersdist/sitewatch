# sitewatch

A Raspberry Pi desk light that watches zeiglersdist.com.

| Light | Meaning |
|---|---|
| Dim green | Site is up |
| Fast red flash | Site is down (office internet is fine) |
| Slow purple pulse | Office internet is down, so nothing can be checked |
| Dark | The Pi or the service is not running |

With `BETA_URL` set (default `LAYOUT=split`, `SPLIT=full`), one animation runs
over the whole panel while both sites are up; if the live site goes down the
left half flashes red over it, and if the Aldrich beta goes down the right half
flashes yellow. `SPLIT=lr` or `SPLIT=tb` instead gives each site its own half
with its own animation. Each half reacts on its own, and
the idle animation rotates through `PATTERNS` every `PATTERN_ROTATE` minutes
(default: a set of self-playing retro-style mini-games from `games.py` -
tetris, runner, climber, pong, snake, breakout, invaders, frogger, racer - each
flashing or pulsing on every good check). Set `PATTERN_ROTATE=0` to stay on
`MAIN_PATTERN` (`BETA_PATTERN` for the beta half in `lr`/`tb` layouts). Other
patterns: `tetris` is an auto-playing Tetris in classic piece colours (`TETRIS_COLORS=0`
for the site's colour) whose stack pulses on every good check,
`ripple` is a ring pulsing out from the centre with a white spark on every good
check, `bars` shows the last 8 response times as a bar chart (taller = slower,
`BAR_SCALE` seconds fills the height), `sonar` is a radar sweep that blips on
every good check, and `ekg` is a heartbeat trace. `LAYOUT=strip` instead shows the beta as a solid bar on the bottom two
rows. An internet outage pulses purple over the whole panel either way.

## Hardware

- Raspberry Pi 3 (or Zero 2 W) running Raspberry Pi OS Lite
- BTF-Lighting 8x8 WS2812B panel, 5V
- Geekworm G469 GPIO screw-terminal breakout (or any 40-pin breakout)
- Official 5V 2.5A micro-USB power supply

### Wiring

Use the panel's **input** side, the female JST connector labeled `5V / GND / DIN`.
Plug the mating pigtail from the box into it and screw its three bare wires into
the breakout:

| Panel wire | Label on panel | Breakout terminal |
|---|---|---|
| Red | 5V | 5V (physical pin 2 or 4) |
| **White** | GND | GND (physical pin 6) |
| Green | DIN | GPIO18 (physical pin 12) |

Note that ground is **white** on this panel, not black. Tape off the output
connector and the bare red/black "voltage-adding" wires; they are not used.

Brightness is capped at 25% in software so the panel can safely draw its power
through the Pi. If you ever want it brighter, feed the red/black
voltage-adding wires from a separate 5V 3A supply (tie its ground to the Pi's
ground) and raise `LED_BRIGHTNESS` in `.env`.

## Install

Fresh Pi: copy this folder over (for example with `scp -r sitewatch pi@sitewatch:~`),
then:

```bash
cd ~/sitewatch
sudo bash install.sh
sudo reboot
```

The installer copies everything to `/opt/sitewatch`, builds a virtualenv,
disables onboard audio (GPIO18's PWM is shared with it), and enables a systemd
service that starts on boot and restarts itself if it crashes.

### Updates from GitHub (no PC in the loop)

Once installed, one command turns `/opt/sitewatch` into a checkout of this repo
(`.env`, the venv and the logs are left alone):

```bash
curl -fsSL https://raw.githubusercontent.com/OWNER/sitewatch/main/bootstrap.sh | sudo bash -s OWNER
```

After that `sitewatch-update.timer` runs `update.sh` every 10 minutes: it pulls
`main`, reinstalls requirements if they changed, refreshes the systemd units and
restarts only what changed. Force it with `sudo /opt/sitewatch/update.sh -v`.
Pulls are logged to `logs/update.log`. Bootstrap also turns off Wi-Fi power
saving, which on a Pi 3 can stall the connection and look like an internet outage.

### Status page

`sitewatch-status.service` serves a read-only page on the LAN at
`http://sitewatch.local:8080/`: current state of both sites, recent events, the
log tail, and `/health` as JSON. It only reads the log files.

## Check it

```bash
sudo systemctl status sitewatch
tail -f /opt/sitewatch/logs/sitewatch_*.log
```

Wiring test that cycles green, red flash, and red pulse without touching the
network:

```bash
sudo systemctl stop sitewatch
sudo /opt/sitewatch/venv/bin/python /opt/sitewatch/sitewatch.py --test
sudo systemctl start sitewatch
```

To fake an outage and see it trip, temporarily set `SITE_URL` in
`/opt/sitewatch/.env` to a URL that doesn't exist and restart the service.

## Settings

All in `/opt/sitewatch/.env`; see `.env.example` for every option. The ones you
are most likely to touch:

- `CHECK_INTERVAL` / `FAIL_THRESHOLD` - default is a check every 30 s and an
  alarm after 3 consecutive failures, so a single slow response won't trip it.
- `CHECK_TEXT` - a string that must appear in the page. Set this to something
  from a page that hits the database if you want to catch "site loads but is
  broken" cases, not just "site doesn't answer".
- `ALERT_WEBHOOK_URL` - a Teams or Slack incoming webhook. When set, the script
  also posts a message on every state change.
- `NET_GRACE` - how many times in a row the reference site (Google) must fail
  before the panel goes purple; 2 by default so a Wi-Fi hiccup doesn't count.
- `GREEN_LEVEL` - how bright the idle green glow is.

## Logs

One log file per run in `/opt/sitewatch/logs/`, also echoed to the journal
(`journalctl -u sitewatch`). State changes are logged at ERROR/INFO, every
failed check at WARNING, and an hourly heartbeat while up. Files older than 15
days are deleted automatically.
