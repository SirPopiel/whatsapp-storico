# WhatsApp storico — iPhone come fonte principale

**Le classifiche del precedente database Mac sono provvisorie.** Il flusso corrente verifica ed estrae il backup Finder dell’iPhone, confronta il risultato con il Mac e soltanto dopo genera le classifiche.

## Aggiornamento ogni sei mesi

Completa un backup locale dell’iPhone con Finder, quindi fai doppio clic su `aggiorna.command` oppure esegui:

```bash
bash aggiorna.command
```

Per un backup già in corso:

```bash
bash aggiorna.command --wait
```

Per estrarre e confrontare senza generare classifiche:

```bash
.venv/bin/python iphone_pipeline.py --wait
```

Le istruzioni complete, inclusi i comandi Terminale e i permessi macOS, sono in [ESTRAZIONE_IPHONE.md](ESTRAZIONE_IPHONE.md).

Il programma non ripiega automaticamente sul Mac. Usa WhatsApp Chat Exporter 0.13.0, non modifica il backup originale, conserva le estrazioni e lavora localmente. Le password dei backup cifrati si inseriscono solo nel prompt nascosto del Terminale. Nessuna automazione ricorrente è stata creata.

La pipeline aggiorna anche la dashboard a ogni estrazione. Dopo modifiche grafiche, rigenerala dai dati statistici locali già salvati senza riestrarre l’iPhone:

```bash
python3 build_dashboard.py
```

## Risultati dopo il confronto iPhone/Mac

- `data/iphone-runs/<data-ora>/iphone.json`, `html/`, `txt/`: esportazione originale iPhone.
- `data/iphone-runs/<data-ora>/confronto.json` e `copertura_per_chat.csv`: conteggi, date, conversazioni, copertura per anno/chat, sovrapposizioni e integrazioni.
- `report/dashboard.html`: dashboard locale con grafico mensile/annuale e quota percentuale annua dei messaggi sul totale del periodo selezionato, selettore “Dal” per scegliere l’inizio del periodo cumulativo, recap storico della Top X con conteggi cumulativi o annuali, posizione cumulativa o annuale con scala adattata, pannelli grafico minimizzabili, pulsanti compatti sotto il grafico per attivare/disattivare le serie predefinite e selettore limitato alle chat entrate almeno una volta nella Top 50, classifiche top 50 per totale nel periodo o messaggi del solo anno, ricerca, ingressi/uscite, salite/discese e crescita dei volumi.
- `report/top50_2014-oggi.csv`, `top50_solo_anno.csv`, `classifiche_complete.csv`: classifiche esportabili.
- `report/nomi_unificati.csv`: gruppi di nomi completi identici unificati nelle statistiche; gli identificativi originali restano invariati nei dati grezzi. `aliases.json` resta riservato alle associazioni esplicite tra identità.
- `report/statistiche.json`, `top50_annuali.md`: serie mensile, statistiche strutturate e classifiche leggibili.
- `archive/chats.json`, `archive/index.html`, `archive/html/`, `archive/txt/`: archivio consolidato testuale.
- `data/iphone_archive.sqlite`: archivio incrementale dell’analisi iPhone, separato dal precedente archivio Mac.

Le correzioni private dei nomi vanno in `name_overrides.local.json` (ignorato da Git); il file condiviso `name_overrides.json` resta vuoto nel repository.

Gli allegati e i metadati disponibili restano nell’esportazione originale dell’iPhone. Le pagine dell’archivio consolidato sono trascrizioni testuali; riferimenti agli allegati non equivalgono al recupero di file mancanti.

## Conteggi e deduplicazione

Ogni anno cumulativo include tutti i messaggi conservati fino al 31 dicembre, anche quelli precedenti al 2014. L’anno corrente si ferma all’ultima data disponibile. La classifica annuale usa solo i messaggi di quell’anno. Gli anni si estendono automaticamente fino all’anno corrente.

Totali = inviati + ricevuti. Ogni messaggio vale un’unità: il grafico e le classifiche non analizzano contenuti o allegati. Analisi delle sole conversazioni individuali; esclusi gruppi, canali, broadcast, stati, eventi di sistema di tipo 6 e record di chiamata privi di tipo. I messaggi vCard restano inclusi. I nomi sono quelli disponibili al momento dell’estrazione; le varianti solo di maiuscole/minuscole sono uniformate (per esempio `claudia speranza` → `Claudia Speranza`). Identici nomi completi individuali di almeno due parole vengono accorpati nelle classifiche, mentre etichette brevi come i nomi di marchi restano separate. L’elenco degli accorpamenti è in `report/nomi_unificati.csv`; il codice li ricalcola a ogni aggiornamento.

Confronto tra fonti: identità certa della chat + `key_id` WhatsApp. Nessuna unione per nome. Si aggiungono dal Mac solo record con identificativo stabile non presente nell’iPhone. Record senza chiave stabile sono elencati tra le identità da verificare; i conflitti conservano il dato iPhone e vengono registrati. Le associazioni LID sono ricavate dal database dell’iPhone quando presenti, oppure dichiarate esplicitamente in `aliases.json`.

Aggiornamenti successivi dell’archivio: la chiave stabile evita doppioni e i messaggi precedentemente acquisiti non vengono eliminati. Per i messaggi iPhone privi di chiave si usa un’impronta di timestamp, direzione, tipo, testo e caption, conservando la molteplicità nella singola estrazione. Questo fallback ha limiti: le copie originali restano disponibili per verifica.

`rank_change = posizione precedente − posizione corrente`: positivo significa salita. I maggiori movimenti confrontano l’intera classifica, mostrando le conversazioni nella top 50 di almeno uno dei due anni. I nuovi interlocutori non ricevono una posizione precedente inventata. La crescita confronta i volumi del singolo anno; l’anno corrente parziale non è omogeneo all’anno precedente completo.

## Codice

`iphone_pipeline.py`: verifica, estrazione e confronto. `update.py`: consolidamento e statistiche. `build_dashboard.py`: rigenera l’HTML dai dati statistici locali. `dashboard.html`: template autonomo senza dipendenze web. [WhatsApp Chat Exporter](https://github.com/KnugiHK/WhatsApp-Chat-Exporter) è l’esportatore open source utilizzato.

```bash
python3 -m unittest discover -s tests -v
```

`.gitignore` esclude dati personali, report e ambiente Python dal versionamento. Conserva una copia sicura dell’intera cartella per preservare lo storico; non cancellare gli archivi SQLite o le estrazioni originali.
