# RicettAIo

RicettAIo conserva le ricette localmente nello spazio persistente dell'app e le rende disponibili dal menu laterale di Home Assistant.

## Prima configurazione

L'archivio manuale funziona senza servizi esterni. La configurazione consigliata usa OpenRouter:

1. crea una API key dedicata su OpenRouter;
2. imposta `ai_provider` su `openrouter` e inseriscila in `openrouter_api_key`;
3. lascia la catena predefinita oppure indica in `openrouter_models` modelli separati da virgola;
4. abilita `ai_enabled` e riavvia l'app.

I modelli sono tentati in ordine. OpenRouter usa soltanto endpoint compatibili con i parametri richiesti, senza raccolta dati e con Zero Data Retention. Gemini diretto resta disponibile impostando `ai_provider` su `gemini`.

Per test gratuiti si può usare `openrouter/free` con `openrouter_strict_privacy` disattivato. In questa modalità OpenRouter può usare endpoint che non garantiscono Zero Data Retention: non inviare ricette o informazioni sensibili.

La chiave viene salvata nelle opzioni dell'app e può essere inclusa nei backup Home Assistant. Non viene mai inviata al frontend né scritta nei log applicativi.

## Dati e backup

Database e immagini sono salvati sotto `/data`. L'app usa backup `cold`: durante il backup viene fermata brevemente per ottenere una copia coerente di SQLite.

Le ricette eliminate restano nel cestino per il numero di giorni configurato in `trash_retention_days`.

## Accesso

Nella configurazione standard l'interfaccia è disponibile soltanto tramite Home Assistant Ingress. Non viene pubblicata alcuna porta sull'host.
