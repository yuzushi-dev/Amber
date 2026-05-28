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

## F4d — Locomo adapter + log streaming Redis (consegnato)

**Locomo adapter** (`src/core/admin_ops/application/evaluation/locomo_adapter.py`):
- Carica JSON ufficiale Locomo `{sessions:[{session_id, date, dialog:[{speaker, text}]}], qa:[{question, answer, category, evidence:[session_id]}]}`.
- Proietta su `JudgeSample` con `ground_truth_context` = concatenazione delle session evidence (fallback: tutte le session se evidence vuoto).
- Rubrica estesa `LOCOMO_RUBRIC` (5 voci): relevance, faithfulness, completeness, temporal_consistency, memory_recall.
- CLI: `amber eval locomo-run <file.json> [--judge-provider --judge-model | --mock-answers]`. Framework discriminator = `locomo`.

**Log streaming Redis** (`judge_eval.publish_eval_state` / `publish_eval_log`):
- Su ogni sample il runner pubblica state JSON su `eval:state:{run_id}` (setex 1h) + `eval:{run_id}:status` (pub/sub).
- Log lines su `eval:{run_id}:logs` (pub/sub) + `eval:logs:{run_id}` lista (lpush + ltrim 500).
- Best-effort: nessuna eccezione propagata, no Redis no problem.

**TUI EvalScreen live**:
- Click su riga → polling 2s di `eval:state:{run_id}` via `tui_data.read_eval_state`.
- `ProgressBar` + status text mostrano `status · done/total · progress%`.
- Stop automatico su `completed/failed/cancelled` o quando la chiave Redis scade.
- Decisione: niente pannello log testuale (scelta utente F4d). Per debug puntuale resta `amber eval show <id> --full`.

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
