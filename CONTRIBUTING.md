# Contributing

1. Fork & clone the repository
2. Create a feature branch
3. Make changes with tests
4. Run `make test` and `make lint`
5. Submit a pull request

Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

## Local Development (Without Docker)

1. **Start Infrastructure**
   ```bash
   docker compose up -d postgres neo4j milvus redis minio etcd
   ```

2. **Backend**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   alembic upgrade head
   uvicorn src.api.main:app --reload
   ```

3. **Worker**
   ```bash
   source .venv/bin/activate
   celery -A src.workers.celery_app worker --loglevel=info
   ```

4. **Frontend**
   ```bash
   cd frontend
   npm install
   npm run dev  # Runs on http://localhost:5173
   ```

### Production Build

The frontend ships a `Dockerfile.prod` and a Compose override that serve the built assets through Nginx instead of the Vite dev server.

### Code Style
```bash
make format  # Format code
make lint    # Run linter
make typecheck  # Type checking
```

### Database Migrations
```bash
make migrate-new  # Create migration
make migrate      # Run migrations
```

## Troubleshooting

**Services won't start**
```bash
docker compose logs api
docker compose restart api
```

**Document processing stuck**
```bash
docker compose logs -f worker
# Check worker for errors, restart if needed
```

**Query returns no results**
- Check document processing status
- Verify vector collection exists
- Check embeddings API key

**High memory usage**
- Reduce worker concurrency
- Clear caches
- Adjust Redis maxmemory
