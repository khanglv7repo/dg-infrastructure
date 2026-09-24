# Verification

## 1. Bootstrap and idempotence

```bash
python scripts/ranger/bootstrap.py
python scripts/ranger/bootstrap.py
```

The second run should converge to `unchanged` for stable resources/grants.

## 2. Verification identities

Local runtime verification uses two deliberately different Trino/Ranger
principals:

- `governance-policy-verifier-bot`: policy subject. It has query execution and
  self-identity grants, but no broad baseline data-read grant.
- `governance-verifier-bot`: independent control identity. It additionally has
  baseline read access to the local `financial` catalog.

Backend configuration should map them as:

```dotenv
TRINO_READONLY_USER=governance-policy-verifier-bot
TRINO_VERIFICATION_CONTROL_USER=governance-verifier-bot
```

The two users must remain different. MASK and ROW_FILTER verification relies on
the control user seeing evidence that the policy user should not see.

## 3. System-level authorization

Verify that both identities can execute a Trino query as themselves:

```bash
python - <<'PY'
import trino

for user in (
    "governance-policy-verifier-bot",
    "governance-verifier-bot",
):
    conn = trino.dbapi.connect(
        host="127.0.0.1",
        port=8080,
        user=user,
    )
    cur = conn.cursor()
    print("\nUSER:", user)
    for sql in ["SELECT current_user", "SELECT 1"]:
        cur.execute(sql)
        print(sql, "->", cur.fetchall())
PY
```

Expected: each `current_user` equals the requested technical identity and
`SELECT 1` succeeds.

## 4. Control baseline data authorization

Only the control identity is expected to have unconditional baseline read
access:

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
    print("\n>>>", sql)
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

Do not grant the same broad baseline data access to
`governance-policy-verifier-bot`; otherwise runtime policy verification can
produce false confirmations.

## 5. Policy verification smoke test

Create a policy whose direct USER subject is
`governance-policy-verifier-bot`. After Backend activation and Ranger
reconciliation:

- ALLOW: policy verifier query succeeds.
- DENY: policy verifier query is denied.
- MASK: policy verifier sees Ranger's transformed value while the control user
  provides the unmasked baseline evidence.
- ROW_FILTER: policy verifier sees no violating row while the control user must
  see at least one row outside the filter.

If the control user cannot produce distinguishing evidence, Backend must report
`VERIFICATION_UNAVAILABLE`, not `VERIFICATION_CONFIRMED` or
`RUNTIME_DRIFT`.

## 6. Ranger/Trino policy refresh

After Ranger policy writes, Trino may require a short refresh interval before
the new Ranger policy version is active. Backend verification must therefore
respect the configured eventual-consistency window before classifying a
mismatch as `RUNTIME_DRIFT`.

## 7. Tag policy verification is separate

Technical baseline read does not verify tag propagation. Tag-policy
verification starts only after an OpenMetadata tag is confirmed and Backend
has reconciled the corresponding Ranger ServiceTags/resource association.

Use explicit test principals for business-role checks; do not treat the control
identity as a substitute for a business user/group.
