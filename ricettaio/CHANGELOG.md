# Changelog

## 0.1.6

- Corretta l'incompatibilità dello schema con l'SDK Gemini per i vincoli numerici (exclusiveMinimum).

## 0.1.5

- Mostrato nei log e nell'interfaccia il motivo restituito da Gemini, con API key redatta.

## 0.1.4

- Consentiti gli health check locali quando la modalità Ingress rigorosa è attiva.

## 0.1.3

- Rimosso il profilo AppArmor personalizzato non ancora validato su Supervisor.
- Ripristinato il profilo di protezione predefinito di Home Assistant per evitare blocchi del bootstrap.

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
