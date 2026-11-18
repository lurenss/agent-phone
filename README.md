# Agent Phone

Agent Phone permette a un coding agent di usare Android passo per passo. Con UIAutomator2 legge il testo e i controlli sullo schermo. Può aprire un’app, toccare un pulsante, scrivere in un campo e verificare il risultato.

![Architettura di Agent Phone. Sul Mac la CLI usa wp.py per raggiungere il Raspberry Pi via SSH, oppure usa ADB locale per guidare un telefono USB o un emulatore.](docs/architecture.svg)

## Scegli il dispositivo

Esegui la CLI con Bun dalla cartella del progetto.

| Dove si trova Android | Cosa serve sul Mac | Per elencare i dispositivi |
| --- | --- | --- |
| Telefono collegato al Raspberry Pi | Python 3 e client `wp.py` configurato per walkie-porkie | `./agent-phone devices` |
| Telefono USB o emulatore sul Mac | `uv` e Android SDK Platform-Tools, che include `adb` | `./agent-phone --local devices` |

Per un telefono USB, abilita **Debug USB** e autorizza il Mac sul telefono. Per un emulatore, avvialo dal **Device Manager** di Android Studio.

## Apri le Impostazioni e verifica il risultato

Per un dispositivo sul Mac, copia il seriale da `devices` e sostituisci `emulator-5554` nell’esempio. Per un telefono sul Pi, usa il suo seriale e togli `--local` da ogni comando.

```sh
SERIAL=emulator-5554
./agent-phone --local lease "$SERIAL" --why "Esplorare le impostazioni"
./agent-phone --local open "$SERIAL" com.android.settings --why "Aprire le impostazioni"
./agent-phone --local state "$SERIAL" --why "Verificare l’app in primo piano"
./agent-phone --local snapshot "$SERIAL" --why "Leggere i controlli visibili"
./agent-phone --local release "$SERIAL"
```

Quando le Impostazioni sono in primo piano, `state` mostra `com.android.settings` nel campo `answer.app`. Con `snapshot` leggi etichette e ID da usare per il prossimo tap.

Per vedere tutti i comandi, esegui `./agent-phone --help`. Le istruzioni operative per Codex e Claude Code sono in [AGENTS.md](AGENTS.md).
