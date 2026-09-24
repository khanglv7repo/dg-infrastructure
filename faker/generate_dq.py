"""Generate deterministic data-quality demo data for the governance lab.

The dataset intentionally contains controlled defects across six dimensions:
Completeness, Accuracy, Uniqueness, Consistency, Validity, and Timeliness.
Each defect bucket is disjoint so Data Quality tests can be validated against a
known ground truth in dq_lab.expected_issues.
"""

import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from faker import Faker


def load_project_env() -> None:
    """Load the root .env file and make it authoritative for this process."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        raise FileNotFoundError(
            f"Environment file not found: {env_path}. "
            "Create it from .env.example before running this generator."
        )

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key.strip()] = value


def env_int(name: str, default: int) -> int:
    """Read and validate a non-negative integer environment variable."""
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return value


def copy_rows(conn, table: str, columns: tuple[str, ...], rows: list[tuple], batch_size: int) -> None:
    """Load rows with PostgreSQL COPY in bounded batches."""
    copy_sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                for row in chunk:
                    copy.write_row(row)
        conn.commit()


load_project_env()

seed = env_int("FAKER_SEED", 2026) + 600
batch_size = max(100, env_int("FAKER_BATCH_SIZE", 10_000))
row_count = env_int("DQ_ROWS", 10_000)
issues_per_dimension = env_int("DQ_ISSUES_PER_DIMENSION", 100)

if issues_per_dimension == 0:
    raise ValueError("DQ_ISSUES_PER_DIMENSION must be greater than zero")
if issues_per_dimension % 2 != 0:
    raise ValueError("DQ_ISSUES_PER_DIMENSION must be even so uniqueness defects can be paired")
if row_count < issues_per_dimension * 6:
    raise ValueError(
        "DQ_ROWS must be at least 6 * DQ_ISSUES_PER_DIMENSION "
        "so the six defect buckets do not overlap"
    )

fake = Faker("en_US")
Faker.seed(seed)
random.seed(seed)

pg_host = os.getenv("FAKER_LOCAL_PGHOST", "127.0.0.1")
pg_port = os.getenv("FAKER_LOCAL_PGPORT", "5432")
pg_database = os.getenv("FINANCIAL_DB", "financial_db")
pg_user = os.getenv("POSTGRES_SUPERUSER", "postgres")
pg_password = os.getenv("POSTGRES_SUPERUSER_PASSWORD")
trino_user = os.getenv("TRINO_DB_USER", "trino_reader")

if not pg_password:
    raise RuntimeError("POSTGRES_SUPERUSER_PASSWORD is missing from the project .env file")

print(f"Connecting to PostgreSQL: {pg_user}@{pg_host}:{pg_port}/{pg_database}")
print(
    f"DQ demo rows={row_count:,}, injected issues per dimension={issues_per_dimension:,}, "
    f"clean rows={row_count - issues_per_dimension * 6:,}"
)

conn = psycopg.connect(
    host=pg_host,
    port=pg_port,
    dbname=pg_database,
    user=pg_user,
    password=pg_password,
    connect_timeout=15,
)

DDL = """
CREATE SCHEMA IF NOT EXISTS dq_lab;

DROP VIEW IF EXISTS dq_lab.quality_validation;
DROP VIEW IF EXISTS dq_lab.detected_quality_issues;
DROP VIEW IF EXISTS dq_lab.expected_issue_summary;
DROP TABLE IF EXISTS dq_lab.expected_issues;
DROP TABLE IF EXISTS dq_lab.customer_profile;
DROP TABLE IF EXISTS dq_lab.customer_reference;
DROP TABLE IF EXISTS dq_lab.country_reference;

CREATE TABLE dq_lab.country_reference (
    country_code char(2) PRIMARY KEY,
    country_name varchar(100) NOT NULL UNIQUE
);

CREATE TABLE dq_lab.customer_reference (
    reference_id bigint PRIMARY KEY,
    customer_number varchar(24) NOT NULL UNIQUE,
    full_name varchar(200) NOT NULL,
    email varchar(255) NOT NULL,
    phone varchar(40),
    country_code char(2) NOT NULL,
    country_name varchar(100) NOT NULL,
    segment varchar(40) NOT NULL,
    annual_income numeric(14,2) NOT NULL,
    customer_status varchar(30) NOT NULL,
    source_updated_at timestamptz NOT NULL
);

-- Intentionally permissive: Data Quality should detect bad records instead of
-- PostgreSQL constraints rejecting them before they can be tested.
CREATE TABLE dq_lab.customer_profile (
    record_id bigint PRIMARY KEY,
    reference_id bigint NOT NULL,
    customer_number varchar(24),
    full_name varchar(200),
    email varchar(255),
    phone varchar(40),
    country_code char(2),
    country_name varchar(100),
    segment varchar(40),
    annual_income numeric(14,2),
    customer_status varchar(30),
    source_updated_at timestamptz,
    ingested_at timestamptz NOT NULL
);

CREATE TABLE dq_lab.expected_issues (
    issue_id bigserial PRIMARY KEY,
    record_id bigint NOT NULL,
    dimension varchar(20) NOT NULL,
    column_name varchar(100) NOT NULL,
    rule_code varchar(100) NOT NULL,
    description text NOT NULL,
    UNIQUE (record_id, dimension)
);

CREATE INDEX idx_dq_customer_number ON dq_lab.customer_profile(customer_number);
CREATE INDEX idx_dq_reference_id ON dq_lab.customer_profile(reference_id);
CREATE INDEX idx_dq_source_updated_at ON dq_lab.customer_profile(source_updated_at);
CREATE INDEX idx_dq_expected_dimension ON dq_lab.expected_issues(dimension);
"""

with conn.cursor() as cur:
    cur.execute(DDL)
conn.commit()

countries = [
    ("US", "United States"),
    ("CA", "Canada"),
    ("GB", "United Kingdom"),
    ("AU", "Australia"),
    ("SG", "Singapore"),
    ("DE", "Germany"),
]
segments = ["Enterprise", "Mid-Market", "Small Business", "Consumer", "Strategic"]
statuses = ["Active", "Inactive", "Prospect", "Churned"]
now = datetime.now(timezone.utc).replace(microsecond=0)

with conn.cursor() as cur:
    cur.executemany(
        "INSERT INTO dq_lab.country_reference(country_code, country_name) VALUES (%s, %s)",
        countries,
    )
conn.commit()

reference_rows: list[tuple] = []
profile_rows: list[tuple] = []
expected_rows: list[tuple] = []

completeness_end = issues_per_dimension
accuracy_end = issues_per_dimension * 2
uniqueness_end = issues_per_dimension * 3
consistency_end = issues_per_dimension * 4
validity_end = issues_per_dimension * 5
timeliness_end = issues_per_dimension * 6
uniqueness_start = accuracy_end + 1

for record_id in range(1, row_count + 1):
    reference_id = record_id
    customer_number = f"CUST-DQ-{record_id:08d}"
    full_name = fake.name()
    email = f"customer{record_id:08d}@example.test"
    phone = f"+1-202-555-{record_id % 10_000:04d}"
    country_code, country_name = random.choice(countries)
    segment = random.choice(segments)
    annual_income = Decimal(random.randrange(30_000_00, 500_000_00)) / Decimal("100")
    customer_status = random.choices(statuses, weights=[70, 10, 15, 5], k=1)[0]
    source_updated_at = now - timedelta(hours=random.randint(0, 72))

    reference_rows.append(
        (
            reference_id,
            customer_number,
            full_name,
            email,
            phone,
            country_code,
            country_name,
            segment,
            annual_income,
            customer_status,
            source_updated_at,
        )
    )

    observed_customer_number = customer_number
    observed_full_name = full_name
    observed_email = email
    observed_country_code = country_code
    observed_country_name = country_name
    observed_annual_income = annual_income
    observed_source_updated_at = source_updated_at

    if record_id <= completeness_end:
        observed_full_name = None
        expected_rows.append(
            (record_id, "Completeness", "full_name", "not_null", "Required customer name is NULL")
        )
    elif record_id <= accuracy_end:
        observed_annual_income = annual_income + Decimal("12345.67")
        expected_rows.append(
            (
                record_id,
                "Accuracy",
                "annual_income",
                "matches_reference",
                "Observed annual income differs from the authoritative reference value",
            )
        )
    elif record_id <= uniqueness_end:
        local_index = record_id - uniqueness_start
        pair_first_id = uniqueness_start + (local_index // 2) * 2
        observed_customer_number = f"CUST-DQ-{pair_first_id:08d}"
        expected_rows.append(
            (
                record_id,
                "Uniqueness",
                "customer_number",
                "unique",
                "Customer business key is duplicated within the observed dataset",
            )
        )
    elif record_id <= consistency_end:
        current_index = countries.index((country_code, country_name))
        observed_country_code = countries[(current_index + 1) % len(countries)][0]
        expected_rows.append(
            (
                record_id,
                "Consistency",
                "country_code,country_name",
                "country_code_name_match",
                "Country code and country name disagree with the reference mapping",
            )
        )
    elif record_id <= validity_end:
        observed_email = f"invalid-email-{record_id}"
        expected_rows.append(
            (
                record_id,
                "Validity",
                "email",
                "email_regex",
                "Email does not match the accepted email format",
            )
        )
    elif record_id <= timeliness_end:
        observed_source_updated_at = now - timedelta(days=180 + (record_id % 90))
        expected_rows.append(
            (
                record_id,
                "Timeliness",
                "source_updated_at",
                "max_age_30d",
                "Source record is older than the 30-day freshness SLA",
            )
        )

    profile_rows.append(
        (
            record_id,
            reference_id,
            observed_customer_number,
            observed_full_name,
            observed_email,
            phone,
            observed_country_code,
            observed_country_name,
            segment,
            observed_annual_income,
            customer_status,
            observed_source_updated_at,
            now,
        )
    )

copy_rows(
    conn,
    "dq_lab.customer_reference",
    (
        "reference_id",
        "customer_number",
        "full_name",
        "email",
        "phone",
        "country_code",
        "country_name",
        "segment",
        "annual_income",
        "customer_status",
        "source_updated_at",
    ),
    reference_rows,
    batch_size,
)
copy_rows(
    conn,
    "dq_lab.customer_profile",
    (
        "record_id",
        "reference_id",
        "customer_number",
        "full_name",
        "email",
        "phone",
        "country_code",
        "country_name",
        "segment",
        "annual_income",
        "customer_status",
        "source_updated_at",
        "ingested_at",
    ),
    profile_rows,
    batch_size,
)
copy_rows(
    conn,
    "dq_lab.expected_issues",
    ("record_id", "dimension", "column_name", "rule_code", "description"),
    expected_rows,
    batch_size,
)

VIEWS = """
CREATE OR REPLACE VIEW dq_lab.expected_issue_summary AS
SELECT dimension, count(*) AS expected_issue_count
FROM dq_lab.expected_issues
GROUP BY dimension;

CREATE OR REPLACE VIEW dq_lab.detected_quality_issues AS
SELECT record_id, 'Completeness'::varchar AS dimension
FROM dq_lab.customer_profile
WHERE full_name IS NULL OR btrim(full_name) = ''

UNION ALL

SELECT p.record_id, 'Accuracy'::varchar AS dimension
FROM dq_lab.customer_profile p
JOIN dq_lab.customer_reference r ON r.reference_id = p.reference_id
WHERE p.annual_income IS DISTINCT FROM r.annual_income

UNION ALL

SELECT p.record_id, 'Uniqueness'::varchar AS dimension
FROM dq_lab.customer_profile p
JOIN (
    SELECT customer_number
    FROM dq_lab.customer_profile
    GROUP BY customer_number
    HAVING count(*) > 1
) d ON d.customer_number = p.customer_number

UNION ALL

SELECT p.record_id, 'Consistency'::varchar AS dimension
FROM dq_lab.customer_profile p
LEFT JOIN dq_lab.country_reference c ON c.country_code = p.country_code
WHERE c.country_code IS NULL OR c.country_name IS DISTINCT FROM p.country_name

UNION ALL

SELECT record_id, 'Validity'::varchar AS dimension
FROM dq_lab.customer_profile
WHERE email IS NULL
   OR email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'

UNION ALL

SELECT record_id, 'Timeliness'::varchar AS dimension
FROM dq_lab.customer_profile
WHERE source_updated_at IS NULL
   OR source_updated_at < now() - interval '30 days';

CREATE OR REPLACE VIEW dq_lab.quality_validation AS
WITH expected AS (
    SELECT dimension, count(*) AS expected_count
    FROM dq_lab.expected_issues
    GROUP BY dimension
), detected AS (
    SELECT dimension, count(*) AS detected_count
    FROM dq_lab.detected_quality_issues
    GROUP BY dimension
)
SELECT
    expected.dimension,
    expected.expected_count,
    COALESCE(detected.detected_count, 0) AS detected_count,
    expected.expected_count = COALESCE(detected.detected_count, 0) AS counts_match
FROM expected
LEFT JOIN detected USING (dimension)
ORDER BY expected.dimension;
"""

with conn.cursor() as cur:
    cur.execute(VIEWS)
    quoted_role = '"' + trino_user.replace('"', '""') + '"'
    cur.execute(f"GRANT USAGE ON SCHEMA dq_lab TO {quoted_role}")
    cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA dq_lab TO {quoted_role}")
    cur.execute("ANALYZE dq_lab.customer_reference")
    cur.execute("ANALYZE dq_lab.customer_profile")
    cur.execute("ANALYZE dq_lab.expected_issues")
    cur.execute("SELECT dimension, expected_count, detected_count, counts_match FROM dq_lab.quality_validation")
    validation = cur.fetchall()
conn.commit()
conn.close()

print("DQ validation summary:")
all_match = True
for dimension, expected_count, detected_count, counts_match in validation:
    print(
        f"  {dimension:<12} expected={expected_count:>6} "
        f"detected={detected_count:>6} match={counts_match}"
    )
    all_match = all_match and counts_match

if not all_match:
    raise RuntimeError("Generated DQ ground truth does not match the detector views")

print("Six-dimension DQ demo dataset generated successfully in schema dq_lab.")
