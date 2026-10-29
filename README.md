# e-codices PDF Downloader

**e-codices PDF Downloader** permette di scaricare in un unico PDF le riproduzioni digitali di un manoscritto disponibile su [e-codices](https://www.e-codices.ch/).

L'applicazione si usa direttamente nel browser: non occorre installare programmi o conoscere la linea di comando.

## Come si usa

1. Apri la pagina web di **e-codices PDF Downloader**.
2. Vai su [e-codices](https://www.e-codices.ch/) e apri il manoscritto che ti interessa.
3. Copia l'indirizzo della pagina dal browser e incollalo nel campo **Indirizzo del manoscritto** dell'applicazione.
4. Seleziona la **Qualità delle immagini**.
5. Fai clic su **Genera PDF**.
6. Segui l'avanzamento del download. Al termine, fai clic su **Scarica il PDF** per salvare il documento sul computer.

### Esempio

Per scaricare il manoscritto *St. Gallen, Stiftsbibliothek, Cod. Sang. 908*, incolla questo link:

`https://www.e-codices.ch/en/doubleview/csg/0908/280b/`

Il programma tenterà di recuperare tutte le immagini del manoscritto, non soltanto quella indicata nell'indirizzo.

## Qualità delle immagini

| Opzione | Caratteristiche |
| --- | --- |
| **Veloce · 1200 px** | File più leggero e download generalmente più rapido; adatto a una consultazione preliminare. |
| **Consigliata · 2000 px** | Buon compromesso tra leggibilità e dimensione del PDF. |
| **Alta definizione · 3000 px** | Più dettagliata, indicata per esaminare particolari del manoscritto. |
| **Originale · dimensione massima** | Richiede più tempo e può produrre un file molto grande. |

*Le dimensioni effettive dipendono dalle immagini messe a disposizione da e-codices.*

## Funzionalità

- Accetta i normali collegamenti alle pagine di visualizzazione di e-codices e gli indirizzi dei manifest IIIF compatibili.
- Identifica automaticamente il manoscritto dal collegamento fornito.
- Recupera le riproduzioni secondo l'ordine stabilito dal manifest IIIF.
- Scarica più immagini contemporaneamente, quando il server lo permette.
- Riunisce le riproduzioni in **un solo PDF**.
- Mostra lo stato dell'elaborazione e consente di scaricare il PDF quando è pronto.

## Domande frequenti

**Devo installare qualcosa?**  
No. Se l'applicazione è già pubblicata online, bastano un browser e una connessione Internet.

**Devo inserire il link di ogni carta?**  
No. È sufficiente il collegamento a una pagina del manoscritto: il programma prova a recuperare l'intera sequenza delle riproduzioni.

**Posso chiudere la pagina durante l'elaborazione?**  
È preferibile lasciarla aperta fino alla comparsa del pulsante **Scarica il PDF**. Il documento generato viene conservato temporaneamente (circa un'ora).

**Perché il download può essere lento o non riuscire?**  
Il tempo dipende dal numero di immagini, dalla loro risoluzione, dalla velocità del server di e-codices e dalle risorse disponibili sul servizio che ospita l'applicazione. Se compare un errore, verifica il link e riprova più tardi, eventualmente scegliendo una risoluzione inferiore.

**Le immagini sono sempre disponibili?**  
No. Alcuni manoscritti o immagini possono essere temporaneamente inaccessibili; il programma non può aggirare i limiti tecnici o le restrizioni imposte dai server di origine.

## Uso delle riproduzioni

Le immagini provengono da **e-codices** e dalle biblioteche che conservano i manoscritti. Prima di pubblicare o riutilizzare le riproduzioni, consulta le condizioni d'uso e le indicazioni di attribuzione relative al singolo manoscritto.

---

*Nota: il programma è un progetto indipendente e non è un servizio ufficiale di e-codices.*
