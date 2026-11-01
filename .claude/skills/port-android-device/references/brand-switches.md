# Developer switches some brands need before adb input works

USB debugging alone lets adb read a screen on every Android device. Some brands add a second switch before adb may
inject a tap, a key or text. Without it, agent-phone reads fine, and its inputs fail or are refused at the server.
The settings below are what each brand calls the switch on recent versions. The menus move between versions, so
when `facts.py` names a brand here, the owner checks the device and says what they found.

| Brand | Developer options switch | What happens without it |
| --- | --- | --- |
| Xiaomi, Redmi, POCO (MIUI, HyperOS) | USB debugging (Security settings). It needs a SIM and a Mi account sign-in to turn on. | Taps and keys are refused (INJECT_EVENTS), while reads work. |
| OPPO, realme, OnePlus (ColorOS, OxygenOS 12 and later) | Disable permission monitoring | Input can be refused, or the server cannot start. |
| vivo (Funtouch OS, OriginOS) | USB debugging (Security settings) | Taps and keys are refused. |
| Huawei, Honor (EMUI, MagicOS) | Allow ADB debugging in charge only mode, when the device only charges over USB | adb does not see the device. |
| Samsung (One UI) | None. Auto Blocker, when it is on, blocks USB commands: turn it off for the run. | adb does not see the device, or the computer's key prompt never shows. |

Notes for the run:
- A brand switch is the owner's to flip. It is a setting on their device, and some of these switches need their
  account. Ask, then check the change with `facts.py` and the survey's journey, which proves key and swipe input.
- If a brand not in this table refuses input, record the error code the survey printed and the brand's version in
  the card, and add a row here once the cause is known.
