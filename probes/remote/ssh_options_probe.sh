#!/bin/sh
# Proves the authorized_keys line and the ControlMaster calls of docs/design/remote.md against a
# throwaway sshd on 127.0.0.1. It touches no phone and no adb server, and it reads no ssh config of
# the user (`-F /dev/null`). Its files live in its own folder and in one folder under /tmp, which
# the length check needs because a control socket path must be short. Keys are made for the run,
# and everything is deleted at the end.
#
#   sh probes/remote/ssh_options_probe.sh     prints one line per check: PASS or FAIL, and what was seen
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RUN="$HERE/run"
rm -rf "$RUN" && mkdir -p "$RUN/www" && chmod 700 "$RUN"
SSHD_PORT=${SSHD_PORT:-22977}
WEB_PORT=${WEB_PORT:-22978}
CM="$RUN/cm.sock"
SHORT_DIR=$(mktemp -d /tmp/ap-cm.XXXXXX)

cleanup() {
  ssh $BASE -o ControlPath="$CM" -O exit probe >/dev/null 2>&1
  [ -f "$RUN/sshd.pid" ] && kill "$(cat "$RUN/sshd.pid")" 2>/dev/null
  [ -n "${WEB_PID:-}" ] && kill "$WEB_PID" 2>/dev/null
  [ -n "${SOCKET_PID:-}" ] && kill "$SOCKET_PID" 2>/dev/null
  rm -rf "$RUN" "$SHORT_DIR"
}
trap cleanup EXIT

for key in host_key client_key loose_key open_key none_key shut_key; do
  ssh-keygen -q -t ed25519 -N '' -f "$RUN/$key"
done

cat > "$RUN/forced.sh" <<'EOF'
#!/bin/sh
echo "who=$2 original=[${SSH_ORIGINAL_COMMAND-}] tty=$(tty >/dev/null 2>&1 && echo yes || echo none)"
EOF
chmod 755 "$RUN/forced.sh"

OPTIONS="command=\"$RUN/forced.sh --who tester\",restrict,port-forwarding,permitopen=\"127.0.0.1:*\",permitlisten=\"127.0.0.1:1\""
echo "$OPTIONS $(cat "$RUN/client_key.pub")" > "$RUN/authorized_keys"
LOOSE="command=\"$RUN/forced.sh --who loose\",restrict,port-forwarding,permitopen=\"127.0.0.1:*\""
echo "$LOOSE $(cat "$RUN/loose_key.pub")" >> "$RUN/authorized_keys"
echo "command=\"$RUN/forced.sh --who open\",restrict,port-forwarding $(cat "$RUN/open_key.pub")" >> "$RUN/authorized_keys"
echo "$LOOSE,permitlisten=\"none\" $(cat "$RUN/none_key.pub")" >> "$RUN/authorized_keys"
echo "$OPTIONS,no-port-forwarding $(cat "$RUN/shut_key.pub")" >> "$RUN/authorized_keys"
chmod 600 "$RUN/authorized_keys"

cat > "$RUN/sshd_config" <<EOF
Port $SSHD_PORT
ListenAddress 127.0.0.1
HostKey $RUN/host_key
PidFile $RUN/sshd.pid
AuthorizedKeysFile $RUN/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
StrictModes no
EOF

/usr/sbin/sshd -f "$RUN/sshd_config" -E "$RUN/sshd.log" || { echo "FAIL  sshd did not start"; exit 1; }
echo "hello from the stand-in device server" > "$RUN/www/index.html"
python3 -m http.server "$WEB_PORT" --bind 127.0.0.1 --directory "$RUN/www" >/dev/null 2>&1 &
WEB_PID=$!

BASE="-F /dev/null -p $SSHD_PORT -o HostName=127.0.0.1 -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityFile=$RUN/client_key -o UserKnownHostsFile=$RUN/known_hosts -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR"
MUX="$BASE -o ControlMaster=auto -o ControlPath=$CM -o ControlPersist=30"

i=0; until ssh $BASE probe true >/dev/null 2>&1 || [ $i -ge 20 ]; do i=$((i+1)); python3 -c 'import time; time.sleep(0.1)'; done

check() {
  if [ "$2" = "$3" ]; then echo "PASS  $1: $3"; else echo "FAIL  $1: expected [$2], saw [$3]"; fi
}
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
fetch() { curl -s -m 3 "http://127.0.0.1:$1/" 2>/dev/null || echo "no answer"; }
kind() {
  if [ -S "$1" ]; then echo "a socket"; elif [ -f "$1" ]; then echo "a file"
  elif [ -d "$1" ]; then echo "a folder"; else echo "nothing"; fi
}
read_socket() {
  python3 -c 'import socket, sys
s = socket.socket(socket.AF_UNIX); s.settimeout(3)
try:
    s.connect(sys.argv[1]); print(s.recv(100).decode().strip() or "no answer")
except OSError:
    print("no answer")' "$1"
}
with_key() { echo "$BASE" | sed "s|client_key|$1|"; }

echo "client: $(ssh -V 2>&1)   server: $(/usr/sbin/sshd -V 2>&1 | head -1)"

check "the forced command runs, and the verb arrives only as data" \
  "who=tester original=[lease 0a1b2c3d4e5f6a7b --task 'two words'] tty=none" \
  "$(ssh $MUX probe "lease 0a1b2c3d4e5f6a7b --task 'two words'")"
check "a shell is not reachable" "who=tester original=[sh -c id] tty=none" "$(ssh $MUX probe sh -c id)"
check "a pty is refused" "who=tester original=[] tty=none" "$(ssh $MUX -tt probe 2>/dev/null | tr -d '\r')"
check "the first call left a master behind" "0" "$(ssh $BASE -o ControlPath="$CM" -O check probe >/dev/null 2>&1; echo $?)"

L=$(free_port)
check "-O forward to 127.0.0.1:<any port> is accepted" "0" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -L 127.0.0.1:$L:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1; echo $?)"
check "the forwarded port reaches the stand-in server" "hello from the stand-in device server" "$(fetch $L)"
check "asking for the same forward again is a no-op that succeeds" "0" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -L 127.0.0.1:$L:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1; echo $?)"
check "a forward on a local port that is taken fails" "nonzero" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -L 127.0.0.1:$WEB_PORT:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1 && echo 0 || echo nonzero)"

L2=$(free_port)
ssh $BASE -o ControlPath="$CM" -O forward -L 127.0.0.1:$L2:localhost:$WEB_PORT probe >/dev/null 2>&1
check "a forward to a host other than the literal 127.0.0.1 carries nothing" "no answer" "$(fetch $L2)"

check "-O forward -L with port 0 is not a way to get a free port" \
  "Bad local forwarding specification '0:127.0.0.1:$WEB_PORT'" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -L 0:127.0.0.1:$WEB_PORT probe 2>&1 | tr -d '\r')"
check "-R is refused, so the key cannot open a listener on the host" "nonzero" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -R 0:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1 && echo 0 || echo nonzero)"

LOOSE_BASE=$(with_key loose_key)
ssh $LOOSE_BASE -o ControlMaster=auto -o ControlPath="$RUN/loose.sock" -o ControlPersist=30 probe list >/dev/null 2>&1
check "without permitlisten, the same key may open a listener on the host with -R" "a port" \
  "$(ssh $LOOSE_BASE -o ControlPath="$RUN/loose.sock" -O forward -R 0:127.0.0.1:$WEB_PORT probe 2>/dev/null | grep -Eq '^[0-9]+$' && echo 'a port' || echo refused)"
ssh $LOOSE_BASE -o ControlPath="$RUN/loose.sock" -O exit probe >/dev/null 2>&1

# A Unix socket on the host: permitlisten names TCP ports only, and permitopen names no path.
PLANTED="$SHORT_DIR/planted.sock"
check "-R to a Unix socket path is accepted with the key's options" "0" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -R "$PLANTED:127.0.0.1:9" probe >/dev/null 2>&1; echo $?)"
check "and the path on the host now holds" "a socket" "$(kind "$PLANTED")"
ssh $BASE -o ControlPath="$CM" -O cancel -R "$PLANTED:127.0.0.1:9" probe >/dev/null 2>&1
check "after -O cancel the path still holds" "a socket" "$(kind "$PLANTED")"
echo "kept" > "$SHORT_DIR/existing"
check "-R to a path that holds a file is refused" "nonzero" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -R "$SHORT_DIR/existing:127.0.0.1:9" probe >/dev/null 2>&1 && echo 0 || echo nonzero)"
check "and the file is as it was" "a file: kept" "$(kind "$SHORT_DIR/existing"): $(cat "$SHORT_DIR/existing")"
mkdir "$SHORT_DIR/folder" && echo "kept" > "$SHORT_DIR/folder/record"
check "-R to a path that holds a folder is refused" "nonzero" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -R "$SHORT_DIR/folder:127.0.0.1:9" probe >/dev/null 2>&1 && echo 0 || echo nonzero)"
check "and the folder is as it was" "a folder: kept" "$(kind "$SHORT_DIR/folder"): $(cat "$SHORT_DIR/folder/record")"

python3 -c 'import socket, sys
s = socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(4)
while True:
    c, _ = s.accept(); c.sendall(b"hello from a socket of the host\n"); c.close()' "$SHORT_DIR/host.sock" &
SOCKET_PID=$!
i=0; until [ -S "$SHORT_DIR/host.sock" ] || [ $i -ge 20 ]; do i=$((i+1)); python3 -c 'import time; time.sleep(0.1)'; done
ssh $BASE -o ControlPath="$CM" -O forward -L "$SHORT_DIR/l.sock:$SHORT_DIR/host.sock" probe >/dev/null 2>&1
check "-L to a Unix socket of the host carries nothing with the key's options" "no answer" "$(read_socket "$SHORT_DIR/l.sock")"
OPEN_BASE=$(with_key open_key)
ssh $OPEN_BASE -o ControlMaster=auto -o ControlPath="$RUN/open.sock" -o ControlPersist=30 probe list >/dev/null 2>&1
ssh $OPEN_BASE -o ControlPath="$RUN/open.sock" -O forward -L "$SHORT_DIR/l2.sock:$SHORT_DIR/host.sock" probe >/dev/null 2>&1
check "control: without permitopen, the same forward reaches the socket" "hello from a socket of the host" "$(read_socket "$SHORT_DIR/l2.sock")"
ssh $OPEN_BASE -o ControlPath="$RUN/open.sock" -O exit probe >/dev/null 2>&1

check "a key with permitlisten=\"none\" cannot log in at all" "refused" \
  "$(ssh $(with_key none_key) probe list >/dev/null 2>&1 && echo "logged in" || echo refused)"
SHUT_BASE=$(with_key shut_key)
ssh $SHUT_BASE -o ControlMaster=auto -o ControlPath="$RUN/shut.sock" -o ControlPersist=30 probe list >/dev/null 2>&1
check "a key that ends with no-port-forwarding gets no Unix socket with -R" "nonzero" \
  "$(ssh $SHUT_BASE -o ControlPath="$RUN/shut.sock" -O forward -R "$SHORT_DIR/shut.sock:127.0.0.1:9" probe >/dev/null 2>&1 && echo 0 || echo nonzero)"
L3=$(free_port)
ssh $SHUT_BASE -o ControlPath="$RUN/shut.sock" -O forward -L 127.0.0.1:$L3:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1
check "but its -L to 127.0.0.1 carries nothing either, so a lease's port is out of reach" "no answer" "$(fetch $L3)"
ssh $SHUT_BASE -o ControlPath="$RUN/shut.sock" -O exit probe >/dev/null 2>&1

check "-O cancel removes the forward" "0" \
  "$(ssh $BASE -o ControlPath="$CM" -O cancel -L 127.0.0.1:$L:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1; echo $?)"
check "the cancelled port answers no more" "no answer" "$(fetch $L)"

ssh $BASE -o ControlPath="$CM" -O forward -R "$SHORT_DIR/left.sock:127.0.0.1:9" probe >/dev/null 2>&1
ssh $BASE -o ControlPath="$CM" -O exit probe >/dev/null 2>&1
python3 -c 'import time; time.sleep(1)'
check "after the connection ended, the path of a -R socket still holds" "a socket" "$(kind "$SHORT_DIR/left.sock")"
SHORT="$BASE -o ControlMaster=auto -o ControlPath=$RUN/short.sock -o ControlPersist=2"
ssh $SHORT probe list >/dev/null 2>&1
ssh $BASE -o ControlPath="$RUN/short.sock" -O forward -L 127.0.0.1:$L:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1
python3 -c 'import time; time.sleep(4)'
check "a forward with no open connection does not keep an idle master alive past ControlPersist" "gone" \
  "$(ssh $BASE -o ControlPath="$RUN/short.sock" -O check probe >/dev/null 2>&1 && echo alive || echo gone)"

check "-O forward with no master fails, and does not connect by itself" "255" \
  "$(ssh $BASE -o ControlPath="$CM" -O forward -L 127.0.0.1:$L:127.0.0.1:$WEB_PORT probe >/dev/null 2>&1; echo $?)"
check "the next plain call makes a new master with no help" "0" \
  "$(ssh $MUX probe list >/dev/null 2>&1; ssh $BASE -o ControlPath="$CM" -O check probe >/dev/null 2>&1; echo $?)"

# ssh reads the value of -o like a line of its config file, so some characters of a path change it.
read_as() {
  ssh -F /dev/null -G -o "ControlPath=$1" probe 2>&1 |
    grep -E '^controlpath |extra arguments|invalid quotes' | tr -d '\r' | sed 's/^.*: //' | head -1
}
check "a plain ControlPath is read as it is written" "controlpath /tmp/ap/farm.sock" "$(read_as /tmp/ap/farm.sock)"
check "a space ends the option" "keyword controlpath extra arguments at end of line" "$(read_as '/tmp/a p/farm.sock')"
check "a quote must close" "invalid quotes" "$(read_as "/tmp/a'p/farm.sock")"
check "a percent sign and a letter are a token, here the port" "controlpath /tmp/a22/farm.sock" "$(read_as '/tmp/a%p/farm.sock')"
check "two backslashes are read as one" 'controlpath /tmp/a\p/farm.sock' "$(read_as '/tmp/a\\p/farm.sock')"
check "a dollar sign with braces names a variable of the environment" "controlpath /tmp/a-there-/farm.sock" \
  "$(AP_PROBE=-there- read_as '/tmp/a${AP_PROBE}/farm.sock')"

# ssh binds the control socket under a temporary name first, the path plus a dot and 16 characters,
# so the longest path that works is the size of sun_path minus 18.
case "$(uname)" in Darwin) SUN=104 ;; *) SUN=108 ;; esac
master_at() {
  path=$(python3 -c 'import sys; base, size = sys.argv[1], int(sys.argv[2]); print(base + "/" + "s" * (size - len(base) - 1))' "$SHORT_DIR" "$1")
  ssh $BASE -o ControlMaster=auto -o ControlPath="$path" -o ControlPersist=5 probe list >/dev/null 2>&1
  if ssh $BASE -o ControlPath="$path" -O exit probe >/dev/null 2>&1; then echo works; else echo fails; fi
}
check "a control socket path of $((SUN - 18)) bytes, sun_path minus 18" "works" "$(master_at $((SUN - 18)))"
check "a control socket path one byte longer" "fails" "$(master_at $((SUN - 17)))"
