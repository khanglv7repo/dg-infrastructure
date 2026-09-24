# Data Quality Faker Lab - 6 dimensions

```text
dq_lab.customer_reference   -> authoritative reference ("truth")
dq_lab.country_reference    -> country code/name mapping
dq_lab.customer_profile     -> observed data containing controlled defects
dq_lab.expected_issues      -> ground truth for injected defects
dq_lab.detected_quality_issues
dq_lab.quality_validation   -> expected vs detected counts
```

The normal CRM Faker remains unchanged. This DQ generator uses a dedicated, intentionally permissive schema so PostgreSQL constraints do not reject bad rows before OpenMetadata Data Quality can evaluate them.

## Generate

From the repository root:

```bash
python3 -m pip install -r faker/requirements.txt
python3 faker/generate_dq.py
```

Defaults:

- `DQ_ROWS=10000`
- `DQ_ISSUES_PER_DIMENSION=100`
- 100 controlled failures for each of the six dimensions
- the six failure buckets are disjoint
- all remaining rows are clean

`DQ_ISSUES_PER_DIMENSION` must be even because the uniqueness bucket is generated in duplicate pairs.

## Six dimensions

| Dimension | Injected defect | Suggested OpenMetadata test |
|---|---|---|
| Completeness | `full_name IS NULL` | `columnValuesToBeNotNull` on `full_name` |
| Accuracy | `annual_income` differs from `customer_reference` | Table Custom SQL, threshold 0 |
| Uniqueness | duplicate `customer_number` pairs | `columnValuesToBeUnique` on `customer_number` |
| Consistency | `country_code` disagrees with `country_name` | Table Custom SQL, threshold 0 |
| Validity | malformed `email` | `columnValuesToMatchRegex` on `email` |
| Timeliness | `source_updated_at` older than 30 days | Table Custom SQL, threshold 0 |

For the three custom dimensions, the exact failing-row SQL is in `faker/dq_tests.sql`.

### Why Timeliness uses Custom SQL here

OpenMetadata's table freshness test answers "has this table received a recent record?". This dataset intentionally mixes fresh and stale rows in one table, so a table-level latest-timestamp check can still pass while stale records exist. The row-level Timeliness demo therefore uses Custom SQL with a 30-day SLA.

## Validate the generator

```sql
SELECT *
FROM dq_lab.quality_validation
ORDER BY dimension;
```

Expected result with defaults: six rows, each with `expected_count=100`, `detected_count=100`, `counts_match=true`.

You can also run:

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d financial_db -f faker/dq_tests.sql
```

## OpenMetadata

The current metadata ingestion configuration includes tables and views and has no schema filter, so `dq_lab` will be discovered on the next ingestion cycle. After discovery, attach the six test cases to `dq_lab.customer_profile`.

For custom SQL tests use strategy `ROWS` and threshold `0`: zero returned bad rows means PASS; one or more returned rows means FAIL.
