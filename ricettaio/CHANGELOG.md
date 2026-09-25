# Changelog

## 0.1.2

- Consentita l'esecuzione delle utility BusyBox necessarie al bootstrap del container.
- Aggiunte le capability minime per preparare `/data` e avviare il servizio come utente non root.
- Consentita la lettura dello script console di Uvicorn da parte dell'interprete Python.

## 0.1.1

- Corretto il profilo AppArmor per consentire a `/bin/sh` di leggere lo script di avvio.

## 0.1.0

- Prima struttura dell'app Home Assistant.
- Archivio locale, ricerca, editor, copertine e cestino.
- Layer AI configurabile con Gemini.
