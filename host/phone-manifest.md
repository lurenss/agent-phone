# phone-manifest

`phone_manifest.py` is one small HTTP service. It lists the phones that are plugged into this computer and says whether each one is healthy.

It checks every phone again every 30 seconds, and a request reads the last check. It only reads. It sends a phone no input and installs nothing. It needs adb and Python 3.11 or newer, which Raspberry Pi OS has from Bookworm on. It does not need agent-phone or [phone-host](README.md).

## Install

Run these commands on the computer with the phones, as its admin. They are written for Raspberry Pi OS.

```sh
sudo apt install -y adb git
git clone https://github.com/lurenss/agent-phone.git
cd agent-phone/host
```

1. Check whether the adb server already runs as a service.

   ```sh
   systemctl is-active adb-server
   ```

   If the answer is `active`, go to step 3.

2. Make the adb server a service. It runs as the account `phones`, and the key that each phone trusts is the key of that account.

   ```sh
   adb kill-server
   sudo useradd --system --create-home --groups plugdev phones
   sudo install -m 644 adb-server.service /etc/systemd/system/
   sudo systemctl enable --now adb-server
   ```

   `adb kill-server` stops a server that you started by hand, because that server holds port 5037. Each phone now asks "Allow USB debugging?". Tick **Always allow from this computer**, then tap Allow. Without the tick, the phone is `unauthorized` again after every restart of the adb server.

3. Install the manifest.

   ```sh
   sudo install -m 755 phone_manifest.py /usr/local/bin/phone-manifest
   sudo install -m 644 phone-manifest.service /etc/systemd/system/
   sudo systemctl enable --now phone-manifest
   curl -s http://127.0.0.1:8037/phones
   ```

The service starts at every boot. systemd starts it again when it stops.

## Flags

| Flag | Description | Default |
| --- | --- | --- |
| `--host` | The address to listen on. | `127.0.0.1` |
| `--port` | The TCP port. `0` picks a free port. | `8037` |
| `--every` | The seconds between two rounds of checks. | `30` |

The flags are on the `ExecStart` line of `/etc/systemd/system/phone-manifest.service`. To change one, edit that line, then run `sudo systemctl daemon-reload` and `sudo systemctl restart phone-manifest`.

The service finds the adb server on port 5037 of 127.0.0.1. Like adb, it reads another port from `ANDROID_ADB_SERVER_PORT`.

## Endpoints

| Request | Status | Body |
| --- | --- | --- |
| `GET /phones` | 200 | The manifest. |
| `GET /phones` while the adb server does not answer | 503 | `{"error": {"type": "adb_down", "message": "The adb server does not answer."}}` |
| `GET /health` | 200 | `{"status": "ok"}`. The adb server answers and every phone is healthy. |
| `GET /health` | 503 | `{"status": "degraded"}`. The adb server does not answer, or a phone has a problem. |
| Any other path | 404 | `{"error": {"type": "not_found", "message": "Try /phones or /health."}}` |

`curl -f` fails on a 503, so a monitor needs no JSON:

```sh
curl -sf http://127.0.0.1:8037/health || echo "a phone needs a look"
```

This manifest has one healthy phone, one phone that waits for a tap on its screen, and one phone that somebody unplugged at 12:41:

```json
{
  "checkedAt": "2026-11-17T13:00:05Z",
  "phones": [
    {
      "serial": "0a1b2c3d4e5f6a7b",
      "model": "SM_J730F",
      "android": "9",
      "state": "device",
      "healthy": true,
      "problem": null,
      "battery": 100,
      "tempC": 26.3,
      "seenAt": "2026-11-17T13:00:05Z"
    },
    {
      "serial": "R58M1234567",
      "model": "",
      "android": "",
      "state": "unauthorized",
      "healthy": false,
      "problem": "unauthorized",
      "battery": null,
      "tempC": null,
      "seenAt": "2026-11-17T13:00:05Z"
    },
    {
      "serial": "emulator-5554",
      "model": "sdk_gphone64_arm64",
      "android": "14",
      "state": null,
      "healthy": false,
      "problem": "gone",
      "battery": null,
      "tempC": null,
      "seenAt": "2026-11-17T12:41:35Z"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `checkedAt` | The time of the round that made this manifest, in UTC. |
| `state` | adb's own word for the phone. It is `null` when adb does not list the phone. |
| `model`, `android` | The model that adb names and the Android release. A phone that does not answer keeps the last values that the service read, and has `""` when it never read one. |
| `healthy` | `true` when `problem` is `null`. |
| `battery`, `tempC` | The battery level in percent and the battery temperature in degrees Celsius, as read in this round. Both are `null` when the phone did not answer in this round. |
| `seenAt` | The time of the last round in which adb listed the phone. |

## Problems

A phone has one problem at a time. The service takes the first row of this table that fits.

| `problem` | Meaning | What to do |
| --- | --- | --- |
| `gone` | adb listed the phone in an earlier round and does not list it now. | Check the cable, the power of the hub and the phone. The row stays until the phone comes back. To drop the row of a phone that you took away, run `sudo systemctl restart phone-manifest`. |
| `unauthorized` | The phone has not accepted the key of this computer. | Tap Allow on the phone, with "Always allow from this computer" ticked. |
| `not_ready` | adb lists the phone in a state that is not `device`, and `state` says which. | `offline`, `authorizing` and `connecting` pass by themselves. `no permissions` means that the account of the adb server may not open the phone's USB port. Check that the account is in the group `plugdev`. `recovery`, `sideload` and `bootloader` mean that the phone did not start Android. |
| `no_answer` | adb says `device`, and the phone did not answer one shell line in 3 seconds. | A busy phone answers again in the next round. Restart a phone that stays so. |
| `booting` | The phone has not finished its start. | Wait. |
| `hot` | The battery is hotter than 45 °C. | Give the phone air, or unplug it for a while. |
| `battery_low` | The battery is below 15 %. | The port does not give the phone enough power. Try another cable or a hub with its own power supply. |

The service writes one line to its journal the first time it sees a phone, each time the problem of a phone changes, and when the adb server stops or starts to answer. So the journal is the history of each phone:

```console
$ journalctl -u phone-manifest -o cat
{"event": "manifest.start", "host": "127.0.0.1", "port": 8037}
{"event": "phone.changed", "serial": "0a1b2c3d4e5f6a7b", "problem": null}
{"event": "phone.changed", "serial": "0a1b2c3d4e5f6a7b", "problem": "gone"}
{"event": "adb.down"}
{"event": "adb.up"}
```

## Reach it from another computer

The service listens on 127.0.0.1 only, so only this computer can read the manifest. It has no login and no encryption, and it shows the serial of every phone.

- Through ssh, with nothing to change: `ssh -N -L 8037:127.0.0.1:8037 <the host>`, then `curl -s http://127.0.0.1:8037/phones` on your own computer. A [phone-host](README.md) key can open this forward (R1-5 in `probes/remote/FINDINGS.md`).
- On a network that you trust: change `--host 127.0.0.1` to `--host 0.0.0.0` in the unit. Every computer on the network can then read `http://<the host's address>:8037/phones`.

## Files

```
phone_manifest.py        the whole service: one file, standard library only
phone-manifest.service   its systemd unit
adb-server.service       a systemd unit for the adb server, for a computer that has none
```

`phone_manifest.py --help` prints the flags. The service asks the adb server over the server's socket and never runs the `adb` binary, which starts a server of its own when it finds none. The only line that it sends a phone is `getprop sys.boot_completed; getprop ro.build.version.release; dumpsys battery`.
