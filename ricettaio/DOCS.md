# RicettAIo

RicettAIo conserva le ricette localmente nello spazio persistente dell'app e le rende disponibili dal menu laterale di Home Assistant.

## Prima configurazione

L'archivio manuale funziona senza servizi esterni. Per attivare l'assistente AI:

1. crea una API key dedicata in Google AI Studio;
2. inseriscila in `gemini_api_key`;
3. indica in `gemini_model` un modello Gemini Flash stabile supportato;
4. abilita `ai_enabled` e riavvia l'app.

La chiave viene salvata nelle opzioni dell'app e può essere inclusa nei backup Home Assistant. Non viene mai inviata al frontend né scritta nei log applicativi.

## Dati e backup

Database e immagini sono salvati sotto `/data`. L'app usa backup `cold`: durante il backup viene fermata brevemente per ottenere una copia coerente di SQLite.

Le ricette eliminate restano nel cestino per il numero di giorni configurato in `trash_retention_days`.

## Accesso

Nella configurazione standard l'interfaccia è disponibile soltanto tramite Home Assistant Ingress. Non viene pubblicata alcuna porta sull'host.
