# Process Historian

CWA process data historian with SQL query interface.

## Running

```bash
./run.sh
```

Listens on port 8080 (set PORT env var to override).

## Credentials
- historian / hist0ry!
- viewer / view2024

## SQL Injection
The `/query` endpoint is intentionally vulnerable to SQL injection for CTF training.
