# Remote findings

Each row records one measurement that the remote mode builds on: what OpenSSH and adb did, and what that obliges the code to do. The columns and the verdicts are the ones of [`probes/android/FINDINGS.md`](../android/FINDINGS.md). A row is never edited after it lands. A later row that changes the picture names the row it supersedes.

Row ids are `R<area>-<n>`. Area 1 is OpenSSH: the `authorized_keys` options and the shared connection. Area 2 is adb: its client against a server on another computer, and the server's socket protocol.

No row needed a phone. The probes run on one computer, against a throwaway sshd on 127.0.0.1, a stand-in adb server that only records requests, and an emulator.

## Environment

Every row was measured on 2026-11-16.

| Fact | Value |
| --- | --- |
| Host | macOS |
| OpenSSH | client and server `OpenSSH_10.3p1, LibreSSL 3.3.6` |
| adb | `Android Debug Bridge version 1.0.41`, `37.0.1-15733141` |
| Device for area 2 | an Android 15 emulator, `emulator-5570`, on the adb server of the same computer |

## Area 1: OpenSSH

The probe is `sh probes/remote/ssh_options_probe.sh`. Its sshd has one key with the options that `phone-host key NAME` prints: `command="... --who NAME",restrict,port-forwarding,permitopen="127.0.0.1:*",permitlisten="127.0.0.1:1"`. Its other keys are controls, each with one option taken away or added. Each row is one or more checks of the probe, and all 36 checks passed in one run.

| id | observed | verdict | action |
| --- | --- | --- | --- |
| R1-1 | `ssh HOST "lease 0a1b2c3d4e5f6a7b --task 'two words'"` ran the forced command. The request arrived in `SSH_ORIGINAL_COMMAND`, quotes included, and the command had no tty. | CONFIRMS | The holder's name comes from `--who` in the forced command. The script splits the request with `shlex` and never hands it to a shell. |
| R1-2 | `ssh HOST sh -c id` ran the forced command with `sh -c id` as data. | CONFIRMS | A key reaches no shell. |
| R1-3 | `ssh -tt HOST` got no pty. | CONFIRMS | `restrict` is enough. No `no-pty` is needed. |
| R1-4 | After one call with `ControlMaster=auto` and `ControlPersist`, `ssh -O check` exits 0. | CONFIRMS | The first call makes the shared connection. agent-phone has no connect step. |
| R1-5 | `ssh -O forward -L 127.0.0.1:<local>:127.0.0.1:<port>` exits 0 for a port the options do not name, and the local port carries data. | CONFIRMS | `permitopen="127.0.0.1:*"` lets a lease use whatever port adb picked. |
| R1-6 | The same `-O forward` a second time exits 0 and changes nothing. | CONFIRMS | `Link.refresh` asks for every forward again without a check. |
| R1-7 | `-O forward` to a local port that is taken exits nonzero. | CONFIRMS | `Link.forward` picks another local port and tries again. |
| R1-8 | A forward to `localhost:<port>` is accepted by the client and carries nothing. | NEW-EDGE | Every forward names the host side as the literal `127.0.0.1`. |
| R1-9 | `ssh -O forward -L 0:127.0.0.1:<port>` prints `Bad local forwarding specification`. | CONTRADICTS | ssh does not pick a free local port for `-L`. `Link.forward` binds port 0 itself to find one. |
| R1-10 | `-O forward -R 0:127.0.0.1:<port>` exits nonzero with `permitlisten="127.0.0.1:1"`. Without that option the same key gets a listening port on the host. | CONFIRMS | The printed options keep `permitlisten`. |
| R1-11 | `-O cancel` exits 0 and the local port stops answering. | CONFIRMS | `Link.close` cancels the forwards its process made. |
| R1-12 | With `ControlPersist=2`, a shared connection that holds one forward and no open channel is gone after 4 s. | NEW-EDGE | A forward does not keep the connection alive. A long session asks for its forwards again at every renewal. |
| R1-13 | With no shared connection, `-O forward` exits 255. The next plain call makes a new connection. | CONFIRMS | A host call always comes before a forward in `Claim.take` and `Claim.keep`. |
| R1-14 | A control socket path of 86 bytes works and one of 87 bytes fails. ssh binds the socket under the path plus 17 characters first, and `sun_path` holds 104 bytes on macOS. | NEW-EDGE | `Link` refuses a longer path with INVALID_ARGS before it calls ssh. The limit is `sun_path` minus 18: 86 on macOS and 90 on Linux. |
| R1-15 | `ssh -O forward -R <path>:127.0.0.1:9` exits 0 with the key's options, and the path on the host then holds a Unix socket. The socket is still there after `-O cancel` and after the connection ended. | CONTRADICTS | `permitlisten` limits TCP listeners only, so R1-10 holds for TCP and not for a path. A key can leave a socket file wherever the account of the key may write. `phone-host` opens its lock and its records without following a link and uses a regular file only. A state folder it cannot use is one JSON refusal. |
| R1-16 | The same `-R` to a path that already holds a file exits nonzero, and the file is as it was. | CONFIRMS | A key cannot replace a file of the host, such as a lease record or `authorized_keys`. It can only take a path that is still free. |
| R1-17 | `-O forward -L <socket>:<socket of the host>` is accepted by the client and carries nothing with the key's options. A key without `permitopen` gets what the host's socket sends. | CONFIRMS | `permitopen="127.0.0.1:*"` names no path, so a key reaches no Unix socket of the host. The mask of the user manager in `host/README.md` is a second guard. |
| R1-18 | A key line with `permitlisten="none"` cannot log in. A key line that ends with `no-port-forwarding` gets no socket with `-R`, and its `-L` to 127.0.0.1 carries nothing. | NEW-EDGE | No option of `authorized_keys` closes R1-15 and keeps the forwards a lease needs. sshd's own `AllowStreamLocalForwarding` does, and that file belongs to the host's admin. |
| R1-19 | `ssh -G -o ControlPath=<path>` reads the path like a line of ssh's config. A space ends the option with `extra arguments at end of line`. A quote is `invalid quotes`. `%p` becomes the port, two backslashes become one, and `${NAME}` becomes the value of that variable. | NEW-EDGE | `Link` refuses a control socket path that holds a space, a quote, `%`, a backslash or `$` with INVALID_ARGS, before it writes anything and before it calls ssh. |
| R1-20 | The same `-R` to a path that holds a folder exits nonzero, and the folder and the file in it are as they were. | CONFIRMS | Supersedes the action of R1-15 where it names a lock. A key cannot take the place of a folder that exists, so `phone-host` takes its `flock` on its state folder and keeps no lock file. It reads a record only when a regular file is at its path and never follows a link. A socket where the folder itself should be refuses every request, so the install guide makes the folder first. |

## Area 2: adb

The probe is `python3 -I probes/remote/adb_facts_probe.py client` for R2-1 to R2-5 and `python3 -I probes/remote/adb_facts_probe.py forward emulator-5570` for R2-6 to R2-17. Every check passed in one run. For R2-13, R2-15 and R2-16 the probe runs `adb connect` to the emulator's own adb port, so the server lists the one emulator under a second serial.

| id | observed | verdict | action |
| --- | --- | --- | --- |
| R2-1 | `adb -H 127.0.0.1 -P <port> devices` with nothing listening exits 1 with `cannot start server on remote host`. Nothing listens on the port 3 s later. | CONFIRMS | `RemoteAdb` runs every command as `adb -H 127.0.0.1 -P <forwarded port>`. A dead tunnel is an error, and no local server takes the tunnel's port. |
| R2-2 | `ADB_SERVER_SOCKET=tcp:127.0.0.1:<port> adb devices` does the same: exit 1, and no server. | CONFIRMS | Either form is safe. The code uses the arguments, so it changes no environment. |
| R2-3 | Control: `adb -P <port> devices`, which means `localhost`, prints `daemon not running; starting now at tcp:<port>` and a server listens there. | CONFIRMS | The address is always written as digits. A client that names `localhost` starts a server of its own. |
| R2-4 | Against a stand-in that answers `host:version` with 40, the 1.0.41 client sends `host:kill` and prints `adb server version (40) doesn't match this client (41); killing...`. It then tries to start a server at that address. | CONFIRMS | Before its first command, `RemoteAdb` compares the local client's number with the host's and refuses with TRANSPORT when they differ. The host's adb server is shared, and one client with another number would kill it for everyone. |
| R2-5 | `adb version` sends the server no request. Against a stand-in that answers 41, `adb devices` sends `host:version` and `host:devices` and no kill. | CONFIRMS | `adb version` is how `RemoteAdb` reads the local number without reaching the host. |
| R2-6 | `host:version` answers `OKAY00040029`. | CONFIRMS | `phone-host list` prints `"adb": 41` from it. |
| R2-7 | `host-serial:<serial>:forward:tcp:0;tcp:9008` answers `OKAYOKAY0005<port>`, and the port listens. | CONFIRMS | `phone-host` asks the server for a free port and reads it from the answer. |
| R2-8 | The same request with that port answers `OKAYOKAY` and no port, and `host:list-forward` still has one row for the serial. | CONFIRMS | A renewal asks for its own port again. That is a no-op when the forward is there, and it brings the forward back when adb lost it. |
| R2-9 | A forward to a port that another process holds answers `FAIL` with `cannot bind listener: Address already in use`. | CONFIRMS | `phone-host` then asks for port 0. The grant carries the new port. |
| R2-10 | `killforward:tcp:<port>` answers `OKAYOKAY`. A second one answers `FAIL` with `listener 'tcp:<port>' not found`. | CONFIRMS | Closing a port that is already closed is not an error for `phone-host`. |
| R2-11 | A forward for a serial the server does not list answers `FAIL0000`, with no message. The server also accepts a device port of 99999. | NEW-EDGE | `phone-host` checks the serial against `host:devices-l` and the device port against 1 to 65535 itself, and it writes its own message. |
| R2-12 | `host-serial:<serial>:forward:norebind:tcp:<port>;tcp:9008` for a port that adb holds answers `FAIL` with `cannot rebind existing socket`. It does so even when the port already points at that serial and that device port. | NEW-EDGE | `norebind` cannot be the first question of a renewal, because it refuses a lease whose port is in order. `phone-host` reads `host:list-forward` first and keeps a port that adb lists for the phone. |
| R2-13 | A plain `forward` for a port that adb holds answers `OKAYOKAY` and moves the port to the new target. Asked with a second serial, it gives the port to that serial. | CONTRADICTS | Supersedes the action of R2-8. A plain forward changes nothing only while the port is still this phone's. adb forgets every forward when it restarts, and the same number can then belong to another phone. A renewal never sends a plain forward for a port it names. |
| R2-14 | `norebind` for a free port makes the forward and answers `OKAYOKAY` and the port as a counted string. For a port that another process holds it answers `FAIL` with `Address already in use`. | CONFIRMS | When adb no longer lists a lease's port, the renewal asks for the same number with `norebind`. adb gives it back when it is free. When adb refuses, `phone-host` asks for port 0 and the grant carries the new port. |
| R2-15 | `norebind` for a port that another serial holds answers `FAIL` with `cannot rebind existing socket`. | CONFIRMS | A renewal cannot take the port of another phone. |
| R2-16 | `host-serial:<serial>:killforward:tcp:<port>` answers `OKAYOKAY` for a port that another serial holds, and the port is closed. | NEW-EDGE | The serial of a `killforward` selects nothing. `phone-host` closes a record's port only while `host:list-forward` lists that port for the record's phone. |
| R2-17 | A process binds port 0 on 127.0.0.1, reads the number and closes the socket. `norebind` for that number then makes the forward, in each of 20 tries. | CONFIRMS | Supersedes the actions of R2-7, R2-9 and R2-14 where `phone-host` asks for port 0. adb's own pick can be a number that sits in the record of another lease, after adb started again and forgot it. So `phone-host` names every port: a free number from the kernel that is in no record, asked for with `norebind`. When adb refuses it, the script asks for the next one, and after 8 the lease is refused. `Link.forward` finds its local port the same way (R1-9). |
