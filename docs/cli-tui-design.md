# Amber CLI + TUI — Design

Stato: skeleton in repo (F4a). Le sezioni F4b/F4c sono pianificate.

## Obiettivi

- Ridurre lo scope della admin UI mantenendo accessibili tutte le operazioni di tuning, gestione modelli, evaluation e backup.
- Fornire una superficie scriptabile (CLI) per CI, runbook e operatori.
- Fornire una superficie interattiva (TUI Textual) per le stesse operazioni, comoda quando si è in SSH.

## Architettura

```
amber <comando> [opzioni]
amber tui                     # apre Textual app
```

- Codice in `src/cli/`.
- Ogni comando importa direttamente i service layer (`src/core/.../application/...`) — niente loopback HTTP.
- Sessioni async aperte via `src/cli/_session.py` (`session_scope`).
- Worker (Celery) richiamato con `task.delay()` come fa la API admin.

Entrypoint: `pyproject.toml` espone `amber = "src.cli.main:app"`. Dopo `uv sync` (o `pip install -e .`) il comando è disponibile.

## F4a — Skeleton CLI (questo PR)

Comandi attivi:

- `amber backup create --scope user_data|full_system [--tenant-id ...]`
- `amber backup list [--status completed|failed|...] [--limit N]`
- `amber backup restore <backup_id> [--mode merge|replace]`
- `amber backup schedule [--enable|--disable] [--frequency daily|weekly] [--time-utc HH:MM] [--retention-count N] [--day-of-week 0..6]`
- `amber tuning show [--field NAME]`
- `amber tuning set <field> <json-value>`
- `amber tuning prompt-edit <field> <path/to/prompt.txt>`
- `amber tuning reset <field>`
- `amber llm show`
- `amber llm set-default <provider> <model> [--temperature ...] [--seed ...]`
- `amber llm set-step <step_id> [--provider ...] [--model ...] [--temperature ...] [--seed ...]`
- `amber llm clear-step <step_id>`
- `amber llm set-embedding <provider> <model>`
- `amber eval list-frameworks`
- `amber eval ragas-run <dataset>`
- `amber tui` → apre `AmberConsole` (Textual)

Limiti volutamente accettati:
- Le sub-commands stampano output Rich; nessun JSON output flag (può arrivare con `--format=json`).
- Non c'è autenticazione: il CLI opera con i privilegi del database. Documentazione operativa raccomanderà di restringerne l'esecuzione.

## F4b — Evaluation framework

Da decidere: **Locomo** vs **LLM-as-judge custom** vs **ragas mantenuto solo CLI**.

Decisione richiesta (tracciata in ticket separato):
- Locomo è long-context multi-turn — adatto per il caso d'uso Amber (conversational RAG).
- ragas è già installato come optional extra; può restare come baseline.
- Custom LLM-as-judge con rubric definite per dominio dà controllo ma costa engineering.

Output comandi previsti:
- `amber eval locomo-run <dataset.jsonl> [--model judge_model]`
- `amber eval compare <run_id_a> <run_id_b>`
- `amber eval report <run_id> [--format md|json|csv]`

I run vengono persistiti in `BenchmarkRun` (tabella già esistente da ragas) — schema da estendere con `framework` discriminator.

## F4c — TUI fleshed-out

Lo skeleton ha 4 tabs placeholder. Per ognuno il piano:

- **Backup tab**: tabella jobs paginata (DataTable), bottoni Create/Restore/Delete, schedule editor inline. Polling via Redis state già esistente (stesso meccanismo della UI web). Auto-refresh ogni 5s.
- **Tuning tab**: tree dei campi config, editor multi-line per prompt (TextArea con preview default), apply/reset.
- **LLMs tab**: matrix view degli step (riga = step, colonna = provider/model attuale vs default). Click per editor.
- **Eval tab**: lista frameworks, picker dataset, log streaming output del worker via Celery result backend o file stream.

Decisioni aperte:
- Connessione DB diretta vs API call. Skeleton usa connessione DB diretta come la CLI; significa che la TUI gira **sul server** e accede a Postgres/Neo4j locali. Per uso remote-headless serve un wrapper SSH oppure pivot su HTTP API.
- Auth nella TUI: oggi nessuna. Se la TUI dovesse girare con permessi non-root in futuro, va riusato lo schema `verify_super_admin` esistente (richiede session token).

## Note operative

- Il container Celery Beat (aggiunto in F2) gestisce `check_due_backups`. Il CLI `amber backup schedule` produce le righe che il Beat consuma — un solo Beat per cluster.
- Eseguire migrazioni alembic prima di usare i comandi backup/llm dopo deploy: `alembic upgrade head`.
- Per testare la TUI senza database: usare ambiente di staging — gli widgets placeholder non chiedono dati al boot.
