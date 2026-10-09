# Procedura corretta: iPhone prima delle classifiche

La fonte principale deve essere il backup Finder dell’iPhone. Il database del Mac serve solo al confronto e a integrare record non sovrapposti con identità verificabile. Le classifiche precedenti del Mac sono provvisorie.

## Un comando ogni sei mesi

Completa il nuovo backup Finder su questo Mac, poi fai doppio clic su `aggiorna.command`. In Terminale:

```bash
cd "/Users/filfedel/Documents/Codex/2026-10-08/worked-for-1m-8s-perfetto-adesso/outputs/whatsapp-storico"
bash aggiorna.command
```

Il programma seleziona il backup locale più recente, verifica `SnapshotState=finished`, controlla i manifest e, se non cifrato, l’integrità SQLite e la presenza dei file dichiarati. Estrae JSON, HTML, TXT con WhatsApp Chat Exporter 0.13.0, verifica che i manifest originali siano rimasti identici, confronta i dataset e solo dopo produce le classifiche. Non usa automaticamente il database Mac quando manca il backup.

Per attendere un backup già in corso:

```bash
bash aggiorna.command --wait
```

Per fare solo estrazione e confronto, fermandosi prima delle classifiche:

```bash
.venv/bin/python iphone_pipeline.py --wait
```

Per un backup conservato altrove:

```bash
.venv/bin/python iphone_pipeline.py --backup "/percorso/backup" --analyze
```

## Comando diretto dell’esportatore

Dopo il completamento del backup attualmente avviato, in Terminale:

```bash
PROJECT_DIR="/Users/filfedel/Documents/Codex/2026-10-08/worked-for-1m-8s-perfetto-adesso/outputs/whatsapp-storico"
BACKUP_DIR="$HOME/Library/Application Support/MobileSync/Backup/00008150-0010248434C0C01C"
RUN_DIR="$PROJECT_DIR/data/estrazione-manuale-$(date +%Y%m%d-%H%M%S)"
umask 077
mkdir -p "$RUN_DIR"
cd "$RUN_DIR"
"$PROJECT_DIR/.venv/bin/wtsexporter" -i -b "$BACKUP_DIR" -o "$RUN_DIR/html" -j "$RUN_DIR/iphone.json" --txt "$RUN_DIR/txt"
```

Non utilizzare `--move-media` sul backup originale. Lo script gestisce le dipendenze aggiuntive per un backup cifrato. La password va inserita solo nel prompt nascosto del Terminale.

## Risultati di verifica e confronto

In `data/iphone-runs/<data-ora>/`:

- `iphone.json`, `html/`, `txt/`: esportazione originale iPhone con i campi e i metadati che l’esportatore rende disponibili.
- `backup-verificato.json`: data, stato, integrità, conteggi, hash dei manifest originali prima/dopo. Per i backup cifrati l’inventario originale non è leggibile prima della decifratura; viene comunque verificato il database WhatsApp estratto.
- `confronto.json`: conteggi, date minime/massime, numero di conversazioni, copertura per anno e per chat per ciascuna fonte.
- `copertura_per_chat.csv`: confronto facilmente consultabile.
- `aliases-verificati.json`: associazioni esplicite e quelle certe presenti nel database LID dell’iPhone, quando disponibile.
- `dataset_integrato.json`: iPhone come base, più record Mac non sovrapposti con identificativo stabile.
- `identita_da_verificare.json`: record Mac senza chiave stabile, esclusi dall’integrazione automatica.
- `conflitti_identificativi.json`: identificativi comuni con contenuto o timestamp diverso; il dato iPhone prevale e gli originali sono conservati.

Deduplicazione: identità della chat verificata + `key_id` WhatsApp. Nessuna unione per semplice uguaglianza del nome. Nessuna somma dei due conteggi. Per le analisi viene usato un archivio separato (`data/iphone_archive.sqlite`), evitando di ereditare automaticamente il precedente archivio Mac. I successivi aggiornamenti conservano i messaggi già acquisiti.

## Permessi macOS

Se compare `Operation not permitted`: Impostazioni di Sistema → Privacy e sicurezza → Accesso completo al disco → abilita **Terminale**, oppure **Codex** se l’esecuzione avviene in Codex. Chiudi e riapri l’app interessata. Non serve disabilitare SIP o cambiare permessi del backup.

Al controllo iniziale l’accesso era consentito, ma Finder mostrava “Last backup on this Mac: Never” con iCloud selezionato. È stato quindi avviato, con autorizzazione dell’utente, il backup locale dell’iPhone. Il telefono deve rimanere collegato fino al completamento.
