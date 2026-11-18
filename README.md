# agent-phone

Una CLI per guidare Android passo per passo. Funziona con i telefoni collegati al Raspberry Pi, i telefoni collegati al Mac via USB e gli emulatori Android sul Mac. L’agente legge la schermata, sceglie una mossa e verifica il risultato.

## Telefono sul Raspberry Pi

Sul Mac servono Bun, Python 3 e il client `wp.py` della skill `driving-phones-via-walkie-api`, con tunnel SSH e token già configurati. La CLI trova lo script nella posizione installata da Claude Code. Per usare un’altra copia, imposta `AGENT_PHONE_WP` al percorso dello script.

Dalla radice del checkout esegui `./agent-phone devices`. Scegli un telefono libero e assegna a `SERIAL` il suo seriale. Questo esempio apre le impostazioni Android, legge l’app in primo piano e torna indietro.

```sh
./agent-phone lease "$SERIAL" --why "Esplorare le impostazioni Android"
./agent-phone open "$SERIAL" com.android.settings --why "Aprire le impostazioni"
./agent-phone state "$SERIAL" --why "Verificare quale app è aperta"
./agent-phone snapshot "$SERIAL" --why "Leggere i controlli disponibili"
./agent-phone key "$SERIAL" BACK --why "Uscire dalle impostazioni"
./agent-phone release "$SERIAL"
```

## Telefono USB o emulatore sul Mac

Sul Mac servono Bun, `uv` e Android SDK Platform-Tools, che include `adb`. La CLI trova ADB nel PATH o nella cartella standard dell’SDK Android sul Mac. Al primo comando locale, `uv` scarica le dipendenze Python.

Per un telefono USB, abilita **Debug USB**, collega il cavo e autorizza il Mac sul telefono sbloccato. Per un emulatore, avvialo dal **Device Manager** di Android Studio. Poi elenca i dispositivi locali.

```sh
./agent-phone --local devices
```

Copia da `devices` un seriale con stato `device`. Ogni comando usa esattamente quel seriale, anche quando il Mac vede più dispositivi. Puoi elencare i dispositivi del Pi con `./agent-phone devices`.

```sh
SERIAL=emulator-5554  # sostituisci con il seriale mostrato sul tuo Mac
./agent-phone --local lease "$SERIAL" --why "Esplorare le impostazioni"
./agent-phone --local open "$SERIAL" com.android.settings --why "Aprire le impostazioni"
./agent-phone --local state "$SERIAL" --why "Verificare l’app in primo piano"
./agent-phone --local snapshot "$SERIAL" --why "Leggere i controlli disponibili"
./agent-phone --local release "$SERIAL"
```

La prenotazione locale dura dieci minuti. Ripeti `lease` per rinnovarla. La CLI registra la prenotazione per seriale e utente macOS. Altri programmi che usano ADB possono interagire con lo stesso dispositivo.

## Trovare e usare un controllo

`snapshot` restituisce testo, descrizione, ID e coordinate degli elementi visibili. Un agente può cercare un’etichetta esatta oppure usare l’ID quando due pulsanti hanno lo stesso testo. Aggiungi `--local` a ogni comando quando usi il Mac. Questi esempi si riferiscono a una schermata di ricerca con il campo `query` e l’etichetta «Risultati».

```sh
./agent-phone find "$SERIAL" --id query --why "Individuare il campo di ricerca"
./agent-phone tap "$SERIAL" --id query --why "Selezionare il campo"
./agent-phone set-text "$SERIAL" "Caffè ☕" --id query --why "Inserire la ricerca"
./agent-phone key "$SERIAL" ENTER --why "Avviare la ricerca"
./agent-phone wait "$SERIAL" "Risultati" --why "Verificare l'apertura dei risultati"
```

Per un tap o una scrittura con selettore, la CLI verifica che ci sia una sola corrispondenza. Zero elementi danno `not_found`, più elementi danno `ambiguous`. Il Pi rilegge la schermata quando esegue l’azione. La UI può cambiare tra le due letture. `set-text` senza ID usa il campo a fuoco. Per un controllo disegnato dall’app, `screenshot` salva un JPEG, `tap SERIAL X Y` tocca un punto e `swipe SERIAL X1 Y1 X2 Y2` esegue un gesto.

Il chiamante decide se un tap è coerente con la richiesta dell’utente, anche per «Pubblica», «Invia» o «Elimina». Il Pi verifica token, diritti e prenotazione. Un exit code 0 conferma la risposta del comando. Per sapere se l’app ha raggiunto l’obiettivo, leggi di nuovo la schermata o usa `wait`. Se il trasporto perde la risposta, osserva lo stato prima di decidere come procedere.

## Come leggere il codice

1. [src/cli.ts](src/cli.ts) traduce i comandi dell’agente. Segui il ramo `tap` per vedere il controllo di unicità e l’invio.
2. [src/transport.ts](src/transport.ts) avvia il client scelto. Per raggiungere il Pi, `wp.py` gestisce tunnel, token, prenotazione e registro delle azioni.
3. [src/local.py](src/local.py) seleziona il dispositivo tramite ADB. Usa UI Automator per leggere i controlli e modificare i campi.
4. [tests/cli.test.ts](tests/cli.test.ts) esegue la CLI come processo e verifica quali comandi arrivano al trasporto.

`./agent-phone --help` elenca tutti i comandi. Per sviluppare, esegui `bun install --frozen-lockfile` e `bun run check`. I test usano un telefono simulato a livello del client. La precedente CLI Python, con USB diretto, profili e flussi TOML, è disponibile nella cronologia Git al commit `b09e614`.
