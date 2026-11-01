# Device cards

One card for each device brought up with the port-android-device skill: its facts, whether it passes
done-when 4, the input journey, the screen reads, the apps swept and what had to be fixed. A card is
written by `.claude/skills/port-android-device/scripts/card.py`, which keeps the text under its
`## Fixes and notes`.

The status of a device:

- `works`: agent-phone reads and drives it, and every check passed.
- `works with limits`: it does, with a limit the card names, such as a second display, a language the
  policy does not cover, or a check that failed.
- `blocked`: agent-phone cannot read or drive it. The card names why.


| name | model | Android | language | status | card |
| --- | --- | --- | --- | --- | --- |
| emu-de-35 | Google sdk_gphone64_arm64 | 15 (API 35) | de-DE (not covered) | works with limits | [emu-de-35.md](emu-de-35.md) |
