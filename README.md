# RicettAIo

RicettAIo è un ricettario personale con assistente AI, progettato come app per Home Assistant. Il nucleo locale funziona senza AI; Gemini aggiunge creazione guidata, ricerca conversazionale e variazioni confermabili.

La versione `0.1.0` implementa il primo MVP locale. Le decisioni di prodotto, il modello dati e il piano delle evoluzioni sono raccolti in [SPECIFICHE.md](SPECIFICHE.md).

## Architettura

- frontend React + TypeScript + Vite;
- backend Python + FastAPI;
- database SQLite e ricerca FTS5;
- Gemini Developer API dietro un layer applicativo controllato;
- singolo container con accesso Home Assistant Ingress;
- dati persistenti in `/data` e backup gestito da Home Assistant.

## Sviluppo locale

Backend:

```bash
cd ricettaio/backend
uv sync --group dev
RICETTAIO_DATA_DIR=../data RICETTAIO_AI_PROVIDER=fake uv run uvicorn app.main:app --port 8099 --reload
```

Frontend, in un secondo terminale:

```bash
cd ricettaio/frontend
npm install
npm run dev
```

Vite inoltra `/api` al backend locale. Il provider `fake` permette di provare i flussi AI senza inviare dati a servizi esterni.

Verifiche:

```bash
cd ricettaio/backend && uv run pytest && uv run ruff check .
cd ricettaio/frontend && npm run build && npm run test
```

## App Home Assistant

La directory `ricettaio/` è una app Home Assistant completa e costituisce il suo build context: contiene manifest, container, backend e frontend. La build usa due stage, compila React con Node e installa il backend in un'immagine Python Alpine. In produzione i dati persistenti vivono in `/data`.

### Installazione da GitHub

1. pubblica l'intero contenuto di questo progetto nella radice di una repository GitHub pubblica;
2. in Home Assistant apri **Impostazioni → App → Installa app**;
3. dal menu con i tre puntini scegli **Repository**;
4. aggiungi l'URL HTTPS della repository GitHub;
5. apri la scheda **RicettAIo**, installa l'app e avviala;
6. abilita **Mostra nella barra laterale**.

Il file `repository.yaml` nella radice identifica il progetto come repository di app Home Assistant. La directory `ricettaio/` contiene l'app installabile.

### Installazione locale alternativa

1. copia la directory `ricettaio/` nella directory `/addons` dell'host Home Assistant;
2. ricarica lo store delle app da **Impostazioni → App → Store**;
3. installa **RicettAIo**, avviala e abilita la voce nel menu laterale;
4. lascia l'AI disabilitata oppure configura una API key Gemini e un modello Flash stabile nelle opzioni.

L'archivio, la ricerca, l'editor, le immagini e il cestino funzionano anche senza Gemini. L'app non pubblica porte sull'host e, con l'impostazione predefinita, accetta richieste solo dal proxy Ingress di Home Assistant.

## Licenza

Apache-2.0. Consulta [LICENSE](LICENSE).
