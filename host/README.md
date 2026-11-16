# phone-host

`phone_host.py` runs on the phone host, the computer the phones are plugged into. It answers one question for people and for agent-phone: which phone is free, and who holds each of the others for which task. The phone host needs adb, sshd and this one script. agent-phone runs on each person's own computer and reaches the phones when `AGENT_PHONE_REMOTE` names the host.

The examples use the ssh alias `farm`, the account `phones` on the host, and the people `ada` and `ben`.

## What the phone host needs

- Linux. The script reads its clock and the id of the current boot from the kernel. Where it finds no boot id, it serves nothing.
- An adb server that runs as the account `phones`, listens on 127.0.0.1:5037 only, and is authorized on each phone. Start it from a service that always restarts it, such as a systemd unit with `Restart=always`. Each ssh key reaches that one server, so nobody else can start it again.
- Python 3.10 or newer, standard library only. The script uses `match`.
- `/bin/sh` as the login shell of `phones`, so that no start-up file prints into the script's JSON.

## Authorize the host on each phone

The first time the host's adb server reaches a phone, the phone asks "Allow USB debugging?". Tick **Always allow from this computer**, then tap Allow.

Without the tick, the phone accepts the host's key for that one connection. Every restart of the adb server and every reboot of the host then asks again, and the phone is `unauthorized` until a person taps its screen. This happened on the first install: one restart of the service left the phone unusable from afar.

## Install the script

Run these commands as the admin of the host.

```sh
sudo install -o root -g root -m 755 phone_host.py /usr/local/bin/phone-host
sudo chsh -s /bin/sh phones
sudo systemctl mask "user@$(id -u phones).service"
sudo -u phones mkdir -p -m 700 ~phones/.local/state/phone-host
```

root owns the script, so the account `phones` cannot change the rules that the script enforces. [What a key can do](#what-a-key-can-do) explains the last two commands.

The last command makes the folder where the script keeps its leases. The script locks that folder itself and keeps one file per held phone in it. It reads no other file there. So the `lock` file that an earlier version of the script left is harmless, and you can delete it.

## Add a person

1. Print the options for the person's key:

   ```console
   $ phone-host key ada
   command="/usr/local/bin/phone-host --who ada",restrict,port-forwarding,permitopen="127.0.0.1:*",permitlisten="127.0.0.1:1"
   ```

2. Put that text, a space, and the person's public key on one line of `~phones/.ssh/authorized_keys`. The folder has mode 700 and the file has mode 600, and `phones` owns both.

sshd's own config does not change. `--who` is the name that every lease of this key shows. The person cannot choose it.

## Set up a person's computer

Add the host to `~/.ssh/config`, then connect once by hand to accept the host key.

```
Host farm
    HostName <the host's address>
    Port <the host's ssh port>
    User phones
    IdentityFile ~/.ssh/<the key>
    IdentitiesOnly yes
```

agent-phone calls ssh with `BatchMode=yes`. A key with a passphrase must be in the ssh agent.

## Use it with plain ssh

```console
$ ssh farm
0a1b2c3d4e5f6a7b  SM_J730F            busy  ben: schedule reel 12 (5 min, free in 95 s)
emulator-5554     sdk_gphone64_arm64  free

$ ssh farm list
{"v":1,"adb":41,"phones":[{"serial":"0a1b2c3d4e5f6a7b","model":"SM_J730F","state":"device","lease":{"by":"ben","task":"schedule reel 12","held_s":312,"free_in_s":95,"mine":false}},{"serial":"emulator-5554","model":"sdk_gphone64_arm64","state":"device","lease":null}]}

$ ssh farm lease emulator-5554 --holder by-hand --task "manual check" --ttl 900
{"v":1,"ok":true,"id":"9f2c61d0","port":null,"lease":{"by":"ada","task":"manual check","held_s":0,"free_in_s":900,"mine":true}}

$ ssh farm release emulator-5554 --holder by-hand
{"v":1,"ok":true}
```

ssh may print `PTY allocation request failed` before the table. The key gets no terminal, and `ssh -T farm` does not ask for one.

The exit status is 0 for a yes, 1 when another holder has the phone, and 2 for a request that the script could not serve. An answer that is not a yes has `"ok":false` and one of these in `error`:

| `error` | Exit | Meaning |
| --- | --- | --- |
| `busy` | 1 | Another holder has the phone. `lease` says who, for which task, and for how long. |
| `no_device` | 2 | adb lists no ready phone with that serial. It may be unplugged or `unauthorized`. |
| `usage` | 2 | The script could not read the request. `message` says why. |
| `adb_down` | 2 | The adb server of the host does not answer. |
| `adb` | 2 | The adb server refused a request. `message` is its own text. |
| `host` | 2 | The host cannot serve the request. It has no boot id, its state folder or a record in it cannot be used, or adb opened no port for the lease. `message` says which. |

```console
$ ssh farm lease 0a1b2c3d4e5f6a7b --holder by-hand
{"v":1,"ok":false,"error":"busy","lease":{"by":"ben","task":"schedule reel 12","held_s":312,"free_in_s":95,"mine":false}}
```

## How a lease ends

- A lease ends at its deadline, `--ttl` seconds after the holder last asked. The default is 120 seconds. A holder that crashed, slept or lost its network stops asking, and the phone is free at the deadline. Nobody cleans up.
- A holder is one `--holder` id of one key. agent-phone keeps one id per state root. So two computers of one person are two holders, and the host lets one of them in.
- `--port` gives the lease one port on the host's loopback that reaches that port on the phone. A release closes the port. So does the next holder who takes the phone after the deadline, and that cuts the old holder off from the phone's server.
- `id` in the answer names one unbroken hold of the phone. A holder that finds a new `id` knows that another holder had the phone in between.
- The port stays the same while adb lists it for the phone. An adb server that started again forgets every port. The next renewal then asks for the same number, and gets another one when a second phone has that number by then. The answer always carries the port that works now.
- A restart of the host ends every lease.

A lease is an agreement between trusted people. The adb server does not check it.

## What a key can do

A key with the printed options can do three things. `probes/remote/FINDINGS.md` holds the measurement behind each row id.

- Run `phone_host.py`. Whatever the caller types arrives as words for the script and never reaches a shell.
- Open TCP connections to the loopback of the host: to adb's server, and to the ports of the leases. A connection to adb's server is full control of every phone on the host. Give a key only to a person you trust with the phones.
- Leave a Unix socket file on the host. `ssh -R <path>:127.0.0.1:9` makes a socket at any path that is still free and that `phones` may write to, and the file stays after the connection ends (R1-15). It cannot replace a file or a folder that exists (R1-16, R1-20).

`permitlisten="127.0.0.1:1"` names a port that no user can bind, so `ssh -R` opens no TCP port on the host. It does not cover a path, and no option of `authorized_keys` stops the socket file while it keeps the forwards that a lease needs (R1-18). The script therefore expects a socket at any path that it uses. It locks its state folder and has no lock file. It reads a record only when a regular file is there, never follows a link, and replaces a socket that is in the way of a record. The state folder itself is the one path where a socket stops the script. Every request then fails with `host` and the path, until the admin deletes that file. A key can put a socket there only while the folder does not exist, which is why the install makes the folder. An admin who may change sshd's config can close the gap for good with `AllowStreamLocalForwarding no` in a `Match User phones` block. This guide does not depend on it.

`permitopen="127.0.0.1:*"` names no path, so a key reaches no Unix socket of the host (R1-17). The mask is a second guard for one dangerous socket. A login of `phones` starts its systemd user manager, and the D-Bus socket of that manager, under `/run/user/<uid>/`, can start any command as `phones`. `systemctl mask user@<uid>.service` stops the manager from starting, so the socket does not exist even for a key whose options someone loosened.

Check an install from a person's computer:

```sh
ssh farm                                    # the table
ssh farm sh -c id                           # a usage error from the script, not a shell
ssh -N -L 127.0.0.1:8022:192.0.2.1:22 farm  # then `nc 127.0.0.1 8022`: ssh prints "administratively prohibited"
ssh -N -L /tmp/bus.sock:/run/user/"<uid>"/bus farm   # then `nc -U /tmp/bus.sock`: closed at once
```
