# Verification

## 1. Bootstrap and idempotence

```bash
cd /home/minh_chau/Documents/goto_ssi/dg_lab/platform
python scripts/ranger/bootstrap.py
python scripts/ranger/bootstrap.py
```

The second run should converge to `unchanged` for stable resources/grants.

## 2. System-level authorization

```bash
python - <<'PY'
import trino

conn = trino.dbapi.connect(
    host="127.0.0.1",
    port=8080,
    user="governance-verifier-bot",
)
cur = conn.cursor()

for sql in ["SELECT current_user", "SELECT 1"]:
    print(f"\n>>> {sql}")
    cur.execute(sql)
    print(cur.fetchall())
PY
```

Expected:

```text
current_user -> governance-verifier-bot
SELECT 1     -> 1
```

This verifies self-impersonation and query execution.

## 3. Technical data authorization

```bash
python - <<'PY'
import trino

conn = trino.dbapi.connect(
    host="127.0.0.1",
    port=8080,
    user="governance-verifier-bot",
)
cur = conn.cursor()

for sql in [
    "SHOW CATALOGS",
    "SHOW SCHEMAS FROM financial",
]:
    print(f"\n>>> {sql}")
    cur.execute(sql)
    print(cur.fetchall())
PY
```

Expected: `financial` is visible and schemas are returned.

Then inspect a real schema/table:

```sql
SHOW TABLES FROM financial.<schema>;
SELECT * FROM financial.<schema>.<table> LIMIT 1;
```

## 4. Ranger/Trino policy refresh

After bootstrap writes a policy, Trino may need a short refresh interval before
the new Ranger policy version is active. Trino logs should show a newer policy
version and a successful policy-engine switch.

## 5. Tag policy verification is a separate test

Technical baseline read does not verify Flow B. Tag-policy verification starts
after an OpenMetadata tag is Confirmed and the backend creates a Ranger
resource/tag mapping. Use separate business-role test users for allow/deny PII
checks; do not use `governance-verifier-bot` as a substitute for `pii_readers`.
