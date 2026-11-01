# The commit gate and device protections

Every input passes the policy engine before it is sent. A tap whose element says it would publish, schedule, send, delete, pay, follow, change the system or confirm needs `--commit <effect>`. A deny rule refuses an input whatever the caller grants, and a device profile can protect a package so that `stop` of it is refused. The live checks point the gate at harmless Settings targets through temporary rules, so a gate bug can only open a Settings page.

## Sub-features

- `gate-commit` refuses a tap that a temporary rule makes a commit, with `COMMIT_REFUSED`, and sends nothing.
- `gate-wrong-grant` refuses the same tap when `--commit` grants another effect.
- `gate-deny` refuses a tap that a temporary deny rule names, even with the matching `--commit`.
- `profile-protect` refuses `stop` of a package that a temporary profile protects, with `DENIED`.
- `profile-name` shows the profile that applies in `devices`.

## How to get to it (user POV)

- Run an input command with `--policy <file>`, and with `--commit <effect>`.
- Put a profile with `[device]` and `[[protected]]` tables in `profiles/` under the state root.

## Driving it with evidence.py

Preconditions:

- Doctor shows no `stop` line, and Settings home shows, read by `evidence.py run "$RUN" home -- agent-phone snapshot --settle`.
- Write the temporary files into the run folder. `display-commit.toml` holds one `[[commit]]` rule with `effect = "confirm"`, `words = ["display"]` and `packages = ["com.android.settings"]`. `display-deny.toml` holds that rule and one `[[deny]]` rule with the same words. `state/profiles/phone.toml` names `$SERIAL` and protects both `hev.sockstun` and `com.android.settings`.

Steps:

- **Commit.** Take the ref of `button "Display"`. Run `evidence.py run "$RUN" commit --input -- agent-phone click <ref> --policy "$RUN/display-commit.toml"`. Exit 1, `COMMIT_REFUSED`, `details.effects` `["confirm"]`, `delivery` `not_delivered`. `evidence.py run "$RUN" after-commit -- agent-phone snapshot --settle` still shows Settings home.
- **Wrong grant.** Run the same click with `--commit publish`. `COMMIT_REFUSED` again, with `details.granted` `["publish"]`.
- **Deny.** Run `evidence.py run "$RUN" deny --input -- agent-phone click <ref> --policy "$RUN/display-deny.toml" --commit confirm`. Exit 1, `DENIED`, and `details.rule` is the deny rule's id. Settings home still shows.
- **Protected.** With the temporary state root, run `evidence.py run "$RUN" temp-look --env AGENT_PHONE_HOME="$RUN/state" -- agent-phone snapshot`, then `evidence.py run "$RUN" protected --input --env AGENT_PHONE_HOME="$RUN/state" -- agent-phone stop com.android.settings`. Exit 1, `DENIED`, `details.rule` `profile.protect.com.android.settings.stop`. The `focus` read still names Settings.
- **Profile name.** `evidence.py run "$RUN" devices --env AGENT_PHONE_HOME="$RUN/state" -- agent-phone devices` shows the temporary profile's name.

## Gotchas

- Never point a live gate check at a real commit button, a notification action or a quick-settings tile. A bug would send the commit.
- Never prove the protection with the real protected package, such as `hev.sockstun` on the J7. A bug would stop it and take the phone offline. `evidence.py` refuses an input that names it.
- A temporary state root has its own lock and its own snapshots. Take a snapshot there before an input, or the input fails with `OBSERVE_FIRST`.
- The temporary profile must keep every protection of the real one, because a command under that state root loads only it.
