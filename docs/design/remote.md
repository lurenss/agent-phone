# Remote phones through a phone host

The phones can be plugged into one small computer, such as a Raspberry Pi, and driven from any other computer. This page explains how that works and why it is built this way. [`host/README.md`](../../host/README.md) is the guide for the admin of such a computer, and [`probes/remote/FINDINGS.md`](../../probes/remote/FINDINGS.md) holds the measurements that this page cites by row id.

Three words are used throughout. The **phone host** is the computer the phones are plugged into. It runs adb's server, sshd and one script, [`host/phone_host.py`](../../host/phone_host.py). A **holder** is one agent-phone state root on one computer. A **lease** says that one holder drives one phone for a named task until a deadline.

## What a caller sees

One environment variable switches agent-phone to the phones of a phone host. Its value is a host alias of the user's ssh config.

```console
$ export AGENT_PHONE_REMOTE=farm
$ export AGENT_PHONE_TASK="schedule reel 12"     # optional: what other people read
$ agent-phone devices                            # the host's phones, each with its holder
$ agent-phone snapshot -d 0a1b2c3d4e5f6a7b       # takes the lease, reads, leaves the lease to run out
```

No command is new and no flag is new. A consumer that calls `open_phone()` does not change either. A person without agent-phone asks the host with plain ssh. `ssh farm` prints one line per phone, and `ssh farm list` prints the same facts as JSON.

A phone that another holder drives is `DEVICE_BUSY`. The error names the holder, the task and the seconds until the lease runs out.

## The problem

agent-phone assumed in two places that adb's server runs on the computer that runs agent-phone.

- `adb forward` makes its listener on the server's computer. So the port that `JsonRpc` connects to is on the phone host, where the caller's computer cannot reach it.
- The device lock is a `flock` in the local state root. A second computer cannot see it, so two computers could drive one phone at once.

A third gap is new. Nothing said who uses a phone, or for what.

The phone host must stay small: adb, sshd and one script of the standard library, with no daemon and no change to sshd's own config. A crash or a dropped network must free a phone by itself. A key must reach no shell.

## The lease

The one shared fact is "who drives this phone until when". It is one JSON file per phone on the host. Only `phone_host.py` writes it, under one `flock` on the folder that holds the records, and every write is a rename, so `list` reads without the lock.

`lease` is one table. `decide()` in the script is that table as a function with no clock, no file and no socket in it, so its tests give it the time.

| The record | The asker | The answer |
| --- | --- | --- |
| none, or from another boot | anyone | grant: a new `id`, counted from now |
| the asker's, in time | its holder | renew: the same `id` and port, a later deadline |
| the asker's, late | its holder | renew: nobody held the phone in between, so the `id` stays |
| another's, in time | anyone else | `busy`, and nothing changes |
| another's, late | anyone else | take over: close the old port, grant with a new `id` |

Four decisions carry the design.

**The lease is a record with a deadline, not a live process.** A lease that lives as long as an ssh session would look like today's device lock. But sshd cannot tell a client that vanished from a quiet one unless its config sets a keepalive, and this design may not change that config. A deadline needs nothing from sshd. The holder renews by using the phone. A holder that crashed, slept or lost its network stops renewing, and the phone is free 120 seconds after its last call. The deadline is read from a clock that no one can set, and the record names the boot it belongs to, so a restart of the host voids every lease.

**The lease carries the port.** With `--port 9008` the script opens one port on the host that reaches the phone's server, and stores that port in the record. So one port exists per held phone. The next holder's lease closes the old holder's port. The host itself cuts a holder that missed its deadline off from the phone's server, and the holder's own check is not the only guard.

A port number is only as good as adb's memory of it. An adb server that started again forgets every forward and gives the same numbers out again, a plain `forward` takes a port from another phone, and `killforward` closes a port whatever phone it belongs to (R2-13, R2-16). So the script trusts adb's own list and not its record. A renewal keeps the port while adb lists it for the phone. Otherwise it asks for the same number with `norebind`, which adb refuses when another phone has it by then, and falls back to a new port that the grant carries (R2-12, R2-14, R2-15). The client then refuses with `TRANSPORT` and the caller opens the phone again. A port is closed only while adb lists it for the phone.

The script names every new port, and adb never picks one. The computer of a record's holder may still point at that record's number, late or not. adb knows no record, so after it started again its own pick can be such a number, and the other holder's computer would reach the new phone until the script closed the port again. So the script takes a free number from the kernel, drops one that sits in any record, and asks adb for it with `norebind` (R2-17). When adb refuses the number, the script takes the next one. After 8 it refuses the lease with `host`.

A number whose lease ended, by a release or a takeover, is in no record, and the next lease of any phone can get it. The old holder's computer may still forward to it, and the host has nothing to stop that with. The guard is the old holder's own lease check. A lease passes to another holder only after its deadline, and by then `Claim.keep()` asks the host before every read and input.

**OpenSSH owns the connection.** Every ssh call passes `ControlMaster=auto` with a control socket in the state root. The first call makes the shared connection, later calls reuse it, and OpenSSH closes it after 10 idle minutes (R1-4). agent-phone has no connect step. A connection that is gone is replaced by the next call (R1-13), and a long session asks for its forwards again at every renewal, which is a no-op while they exist (R1-6). ssh needs 45 seconds to see that the network of a connection died. So a request that gets no answer in 20 seconds ends the shared connection with `ssh -O exit`, and the next command makes a new one.

**The hub takes the lease, and the phone keeps it.** `RemoteHub.open()` leases the phone before the backend touches it, and returns a `LeasedPhone`. That wrapper calls `Claim.keep()` before every read and input. `keep` does nothing until a third of the lease has passed, then asks the host again. It measures the age of the grant with the wall clock, because a laptop's monotonic clock stops while the laptop sleeps. A laptop that slept past its deadline asks the host before it sends anything. When the host answers with another `id`, another holder had the phone, and `keep` refuses from then on. Inside `inject` the refusal becomes `NotSent`, so the ledger refunds the permit and the result is `not_delivered`, which is true.

## How one command runs

1. `Settings.from_environment` reads `AGENT_PHONE_REMOTE` and `AGENT_PHONE_TASK`. `open_hub` builds a `RemoteHub`, which connects to nothing yet.
2. `hub.connected()` runs `ssh farm list --holder <id>`. `wire.parse_listing` turns the answer into `Connected` rows, each with its `Lease` or none.
3. Device selection, the policy merge and the local device lock run as they do for a local phone.
4. `hub.open(serial)` runs `ssh farm lease <serial> --holder <id> --task <task> --ttl 120 --port 9008`, then asks the shared connection for a local port that reaches the lease's port.
5. The backend opens the phone. Its `adb forward tcp:0 tcp:9008` is answered with that local port and is not sent. Its other adb commands run as `adb -H 127.0.0.1 -P <port>`, through a second forward to the host's adb server.
6. The command runs against the `LeasedPhone`. When the phone closes, a session releases the lease and a command line leaves it to run out. Leaving `open_hub` cancels the forwards of the process.

A command line runs one process per step. Its lease runs out 120 seconds after the last step, so the steps of one job follow each other with no other computer in between.

## Two facts about adb that shaped the adapter

Both were read in adb's source first and then measured.

- `adb -H 127.0.0.1 -P <port>` never starts a server. With nothing listening it fails with `cannot start server on remote host` (R2-1). A client that names `localhost`, which is the default, starts a server of its own on that port (R2-3). So a dead tunnel is an error and never a second adb server.
- An adb client kills a server whose protocol number differs from its own (R2-4). The host's server is shared, so `RemoteAdb` compares the two numbers before its first command and refuses with `TRANSPORT` when they differ. `phone-host list` carries the host's number for that.

## What holds, and what enforces it

| Invariant | Enforced by |
| --- | --- |
| One holder per phone at a time | The table of `decide()` under `flock`, on the host |
| A lease outlives its holder by 120 seconds at most | The deadline in the record |
| A restart of the host ends every lease | The record names its boot. A host with no boot id serves nothing. |
| A port of the host reaches the phone of one lease only | The script keeps and closes a port by adb's own list. It names every new port, never a number that is in a record, and asks for it with `norebind` (R2-12 to R2-17). |
| An old holder sends nothing through a port number whose lease ended | The number is in no record, so another phone can get it, and the host cannot stop the old holder's computer from forwarding to it. The holder's own check is the guard. After a lease's deadline, `keep()` asks the host before every read and input. |
| An old holder cannot reach the phone's server after a takeover | The host closes its port |
| No read and no input leaves under a stale grant | `LeasedPhone` calls `keep()` first. `tests/test_phone_contract.py` has a rig for it. |
| The name in `by` is the key's owner | `--who` is in the key's forced command, and the request arrives as data (R1-1) |
| A key gets no shell, no pty and no TCP port on the host | `restrict`, `command=` and `permitlisten` (R1-2, R1-3, R1-10) |
| A key reaches no Unix socket of the host | `permitopen` names no path (R1-17). The masked user manager is a second guard. |
| Nothing that a key leaves in the script's state folder is opened, and nothing there stops a lease | The script locks the folder itself and keeps no lock file. It reads a record only when a regular file is at its path, and never follows a link. A key can leave a socket at a path that is free, and not at one that exists (R1-15, R1-16, R1-20). |
| A record that cannot be read never frees its phone | Only a missing file, a socket and a link are no record. Any other fault is a `host` refusal that names the file. |
| The host's shared adb server gets no command that restarts or unplugs it | `RemoteAdb` sends `shell`, `push` and `devices`, answers `forward` itself, and refuses every other command |
| The script and the client agree on the JSON | `tests/test_remote_wire.py` runs the real script and reads its output with `wire.py` |
| Nothing outside `adapters/remote` imports its modules | A rule in `tests/test_architecture.py` |
| The `authorized_keys` options match the script | `phone-host key NAME` prints them. No doc holds a second copy. |
| Every input still comes through `act()` | `tests/test_input_paths.py` names `LeasedPhone.inject` as the one function that may hand a permit on. Its last statement must be that hand-on, once, with the permit it was given. The test plants the wrappers it must catch. |

The local device lock stays. It is taken first and serializes the processes that share a state root, which is what refs and the ledger need. The lease serializes holders. The holder id is a file in the state root, so the processes that share the local lock are the processes that share the lease.

## What it does not do

- It does not reconnect in the middle of a command. The command fails with `TRANSPORT`, and the next command makes a new connection.
- It does not mix local phones and a host's phones in one process.
- It does not stop a key from leaving Unix socket files on the host. No option of `authorized_keys` does, and sshd's config is the admin's (R1-15, R1-18).
- It does not stop a trusted person from running raw `adb` through a forward of their own. A key that can reach adb's server has full control of the phones, and the lease is an agreement between the people who hold keys.
- It does not move refs, traces, snapshots or device profiles to the host. They stay on the computer that drives.

## Trade-offs

- A phone stays taken for up to 120 seconds after a crash, and after the last command of a job at the command line. In exchange the lease needs no process on either side and nothing from sshd.
- Each command line makes two calls to the host, `list` and `lease`. In exchange the host runs no daemon.
- `permitopen="127.0.0.1:*"` lets a key reach every loopback port of the host. In exchange a lease's port is any port that is free, so no pool of ports and no rule for reusing them exists. The key reaches no other host.
- The host cuts off an old holder's port to the phone's server, but not its raw adb. The holder's own check covers that path.
- A session whose lease passed to another holder must be opened again. In exchange it never reads or taps on top of another computer's work.
- `RemoteAdb` reads the arguments of every adb command. It answers `forward` itself, sends `shell`, `push` and `devices`, and refuses the rest. In exchange `adapters/uiautomator2` does not change. A test over the real `U2Hub` fails when the backend words a command another way.
- A request that times out ends the shared connection for every process of that state root. In exchange the next command does not wait on a connection whose network died.
- The local adb client must speak the host's protocol number. In exchange agent-phone needs no adb client of its own.

## Alternatives that lost

| Alternative | Why it lost |
| --- | --- |
| A lease that is an open ssh session holding a `flock` on the host | The host cannot tell a dead client from a quiet one, and a command line would need a holder process between its steps |
| Reach the phone's server through adb's own stream, with no port at all | Each call costs about twice the round trips, and it replaces the measured connection path of `rpc.py` |
| Let the client run `adb forward` through the tunnel | Every process pays two more adb commands, a crashed client leaves its listener on the host, and nothing on the host cuts off an old holder |
| Proxy every adb command through the script | The script becomes an adb proxy with a policy of its own |
| Run agent-phone on the host | It puts the refs, traces and screenshots of several people in one state root, and the host no longer stays small |

## Left for later

- A computer with no device profile for a phone has none of its owner's protections. Remote mode could refuse to open a phone that has no profile on this computer.
- A takeover by another computer does not spend this computer's refs between two commands. The grant's `id` makes that possible.
- A lease call that dies between opening its port and storing its record leaves one forward on the host until adb restarts. Nothing points at it.
- A lease that runs out keeps its port open on the host until the next lease of that phone. agent-phone sends nothing through it without a lease, and the next holder's lease closes it. Only `list` could close it sooner, and `list` takes no lock and changes nothing.
- The adapter reaches the host's adb server on port 5037 only.
- The holder id belongs to a state root. A state root that is copied to a second computer makes both computers one holder.
- A second `open()` of one phone in one process would replace the first claim. No caller does that today.
