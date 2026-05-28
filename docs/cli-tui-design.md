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

## F4b — Evaluation framework (consegnato)

Scelta: **LLM-as-judge custom** come default. Ragas rimane runner legacy. Locomo
resta task aperto (richiede dataset + adapter dedicato).

Backend:
- `BenchmarkRun.framework` (string, default `ragas`) discriminator. Migration
  `20260528_1100_benchmark_framework.py`.
- `src/core/admin_ops/application/evaluation/judge_eval.py`: caricamento JSONL,
  rubrica 3 voci (relevance/faithfulness/completeness) 0-10 → metrica `overall`.
  Tollerante a noise nell'output del judge (regex JSON, fence stripping).

CLI:
- `amber eval list-frameworks`
- `amber eval ragas-run <dataset>` (legacy worker)
- `amber eval judge-run <dataset.jsonl> --judge-provider --judge-model [--api-base --api-key | --mock-answers]`
- `amber eval list-runs [--framework]`
- `amber eval show <run_id> [--full]`
- `amber eval compare <run_id_a> <run_id_b>`
- `amber eval report <run_id> [--format md|json|csv] [--out file]`

Formato dataset JSONL (una riga per sample):
```
{"question": "...", "expected_answer": "...", "contexts": "optional context"}
```

Locomo (planned): adapter che legge il formato Locomo e proietta su
`JudgeSample`, più rubrica estesa con `temporal_consistency`.

## F4c — TUI fleshed-out (consegnato)

Quattro tab funzionanti in `src/cli/tui/screens.py`:

- **Backup**: `DataTable` di job + bottoni Create user_data/full_system, Restore
  merge/replace (sulla riga selezionata), e form Schedule (Switch enabled,
  frequency, time UTC, scope, retention). Refresh manuale via `r` o bottone.
- **Tuning**: prompt editor (TextArea multi-line) con picker tra i 5 prompt
  fields. Load / Save / Reset (drop override).
- **LLMs**: defaults + matrice degli override per-step (riga = step_id, colonne
  provider/model/temperature/seed). Edit avviene via CLI `amber llm set-step` —
  la TUI è read-mostly per non duplicare la logica di provider validation.
- **Eval**: lista runs (DataTable), refresh manuale. Lancio runs sempre via
  CLI per non bloccare la TUI con job lunghi.

Connessione DB diretta — la TUI gira sul server (stessa scelta della CLI). Per
uso remote-headless: SSH + container `worker.Dockerfile` con `command:
amber tui` (vedi docker-compose).

Decisioni aperte (non bloccanti):
- Auth nella TUI: nessuna oggi. Se serve, aggiungere ticket integration con
  `verify_super_admin` (session token).
- Log streaming worker (Eval tab): da fare se servirà watch real-time;
  per ora il polling delle metric su DB è sufficiente.

## Note operative

- Il container Celery Beat (aggiunto in F2) gestisce `check_due_backups`. Il CLI `amber backup schedule` produce le righe che il Beat consuma — un solo Beat per cluster.
- Eseguire migrazioni alembic prima di usare i comandi backup/llm dopo deploy: `alembic upgrade head`.
- Per testare la TUI senza database: usare ambiente di staging — gli widgets placeholder non chiedono dati al boot.
