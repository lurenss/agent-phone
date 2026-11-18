# Istruzioni per Agent Phone

Usa pstack per progettare, modificare e verificare Agent Phone. Il [README](README.md) contiene i prerequisiti e un esempio completo.

## Guidare Android

1. Esegui `devices` e scegli il seriale del dispositivo richiesto. Il Raspberry Pi è la destinazione predefinita. Per USB ed emulatori sul Mac, usa `--local` in ogni comando della sessione.
2. Prenota un dispositivo libero con `lease SERIAL --why TASK`. Indica lo scopo di ogni lettura o azione con `--why`. Il limite è 80 caratteri per la prenotazione e 200 per gli altri comandi.
3. Leggi `state` per conoscere l’app in primo piano, lo schermo e la tastiera. Usa `snapshot` per ottenere testo, descrizione, ID, coordinate e stato di focus dei controlli.
4. Scegli un’azione coerente con la richiesta, anche quando il controllo invia, pubblica o elimina qualcosa. Invia l’azione una volta. Verifica l’effetto con una nuova lettura o con `wait`.
5. Libera il dispositivo con `release SERIAL` quando hai finito, anche se il task si interrompe.

## Selezionare un controllo

- `find` e `tap` accettano il testo esatto o `--id ID`. Usa un ID letto dalla schermata quando più controlli hanno la stessa etichetta. `not_found` indica zero corrispondenze, `ambiguous` più di una. In entrambi i casi, rileggi la schermata.
- `set-text SERIAL TESTO --id ID` sostituisce il contenuto di un campo. Senza ID usa il campo di testo a fuoco. Se il testo inizia con un trattino, metti prima le opzioni e poi `--` seguito dal testo.
- `wait` attende fino a dieci secondi che compaia almeno un elemento con il testo o l’ID richiesto. Per esempio, dopo una ricerca attendi un’etichetta dei risultati.
- Se l’app disegna un controllo che manca da `snapshot`, salva un JPEG con `screenshot SERIAL FILE.jpg`. Usa l’immagine corrente per scegliere le coordinate di `tap SERIAL X Y` o `swipe SERIAL X1 Y1 X2 Y2`.

La CLI scrive i risultati JSON su stdout e gli errori su stderr. Un codice di uscita 0 conferma che il comando ha ricevuto una risposta positiva. Se perdi la risposta a un tap o a una scrittura, osserva lo stato del dispositivo prima di decidere l’azione successiva.

## Collegamento e prenotazioni

**Raspberry Pi.** Agent Phone avvia `wp.py` dalla skill `driving-phones-via-walkie-api`. Il client gestisce il tunnel SSH, il token, la prenotazione e il registro delle azioni. Per usare una copia diversa, imposta `AGENT_PHONE_WP` al percorso di `wp.py`. Walkie-porkie riutilizza il servizio UIAutomator2 sul telefono tra comandi successivi. Per i tap per nome o ID e le scritture per ID, la CLI verifica l’unicità prima dell’invio. Il Pi rilegge il controllo quando agisce. La schermata può cambiare tra le due letture.

**Mac.** La CLI cerca `adb` nel PATH o in `~/Library/Android/sdk/platform-tools/adb` e contatta il server su `127.0.0.1:5037`. Al primo uso, `uv` prepara le dipendenze Python. Se il telefono USB compare come `unauthorized`, sbloccalo e accetta la richiesta di Debug USB. Scegli un seriale con stato `device`.

UIAutomator2 legge la gerarchia dei controlli, esegue i tap per testo o ID e scrive nei campi. ADB gestisce apertura delle app, screenshot, tap per coordinate, swipe e tasti. Quando un comando avvia il servizio UIAutomator2, lo arresta prima di terminare. Nei test di velocità locali, considera anche il tempo di avvio del servizio.

La prenotazione locale dura dieci minuti. Ripeti `lease` per rinnovarla. I processi Agent Phone dello stesso utente macOS condividono la prenotazione e serializzano i comandi per dispositivo. Altri client ADB possono agire sullo stesso telefono.

## Modificare la CLI

- Mantieni sintassi, validazione e testo di `--help` in [src/cli.ts](src/cli.ts).
- Seleziona il client in [src/transport.ts](src/transport.ts). Passa gli argomenti come array. Implementa le operazioni Android locali in [src/local.py](src/local.py).
- Esegui `bun install --frozen-lockfile` per preparare l’ambiente di sviluppo. Prima del commit esegui `bun run check`. I [test della CLI](tests/cli.test.ts) usano client simulati e devono restare indipendenti da telefoni, credenziali e account reali.
