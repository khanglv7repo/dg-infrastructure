"""Generate a large English-language CRM dataset for the governance lab.

The generator runs directly on Ubuntu and loads project settings from ../.env.
It uses PostgreSQL COPY in bounded batches, so millions of rows can be loaded
without keeping the complete dataset in memory.
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


load_project_env()

seed = env_int("FAKER_SEED", 2026)
batch_size = max(1_000, env_int("FAKER_BATCH_SIZE", 10_000))

# Large but laptop-friendly defaults: approximately 2.3 million CRM rows.
customer_count = env_int("CRM_CUSTOMERS", 100_000)
contact_count = env_int("CRM_CONTACTS", 250_000)
lead_count = env_int("CRM_LEADS", 200_000)
opportunity_count = env_int("CRM_OPPORTUNITIES", 150_000)
activity_count = env_int("CRM_ACTIVITIES", 1_000_000)
support_case_count = env_int("CRM_SUPPORT_CASES", 100_000)
campaign_count = env_int("CRM_CAMPAIGNS", 500)
campaign_member_count = env_int("CRM_CAMPAIGN_MEMBERS", 500_000)

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
    "Planned CRM rows: "
    f"customers={customer_count:,}, contacts={contact_count:,}, "
    f"leads={lead_count:,}, opportunities={opportunity_count:,}, "
    f"activities={activity_count:,}, support_cases={support_case_count:,}, "
    f"campaigns={campaign_count:,}, campaign_members={campaign_member_count:,}"
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
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS crm.customers (
    customer_id bigint PRIMARY KEY,
    customer_number varchar(24) NOT NULL UNIQUE,
    customer_type varchar(20) NOT NULL,
    company_name varchar(200),
    first_name varchar(100),
    last_name varchar(100),
    email varchar(255),
    phone varchar(40),
    date_of_birth date,
    industry varchar(100),
    segment varchar(40) NOT NULL,
    annual_revenue numeric(18,2),
    employee_count integer,
    address_line_1 varchar(255),
    city varchar(100),
    state varchar(100),
    postal_code varchar(20),
    country varchar(100) NOT NULL,
    preferred_language varchar(20) NOT NULL,
    marketing_opt_in boolean NOT NULL,
    customer_status varchar(30) NOT NULL,
    acquisition_source varchar(50) NOT NULL,
    assigned_owner varchar(150) NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.contacts (
    contact_id bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES crm.customers(customer_id),
    first_name varchar(100) NOT NULL,
    last_name varchar(100) NOT NULL,
    job_title varchar(150),
    department varchar(100),
    business_email varchar(255),
    personal_email varchar(255),
    mobile_phone varchar(40),
    office_phone varchar(40),
    is_primary boolean NOT NULL,
    contact_status varchar(30) NOT NULL,
    preferred_channel varchar(30) NOT NULL,
    consent_email boolean NOT NULL,
    consent_sms boolean NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.leads (
    lead_id bigint PRIMARY KEY,
    lead_number varchar(24) NOT NULL UNIQUE,
    first_name varchar(100) NOT NULL,
    last_name varchar(100) NOT NULL,
    company_name varchar(200),
    email varchar(255),
    phone varchar(40),
    job_title varchar(150),
    lead_source varchar(50) NOT NULL,
    lead_status varchar(30) NOT NULL,
    lead_score integer NOT NULL,
    estimated_value numeric(18,2),
    industry varchar(100),
    country varchar(100),
    assigned_owner varchar(150) NOT NULL,
    created_at timestamptz NOT NULL,
    converted_at timestamptz
);

CREATE TABLE IF NOT EXISTS crm.opportunities (
    opportunity_id bigint PRIMARY KEY,
    opportunity_number varchar(24) NOT NULL UNIQUE,
    customer_id bigint NOT NULL REFERENCES crm.customers(customer_id),
    opportunity_name varchar(255) NOT NULL,
    sales_stage varchar(50) NOT NULL,
    amount numeric(18,2) NOT NULL,
    probability_percent integer NOT NULL,
    expected_close_date date NOT NULL,
    actual_close_date date,
    loss_reason varchar(150),
    lead_source varchar(50) NOT NULL,
    assigned_owner varchar(150) NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.activities (
    activity_id bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES crm.customers(customer_id),
    contact_id bigint,
    opportunity_id bigint,
    activity_type varchar(30) NOT NULL,
    activity_subject varchar(255) NOT NULL,
    activity_status varchar(30) NOT NULL,
    channel varchar(30) NOT NULL,
    activity_at timestamptz NOT NULL,
    duration_minutes integer,
    outcome varchar(100),
    performed_by varchar(150) NOT NULL,
    notes text
);

CREATE TABLE IF NOT EXISTS crm.support_cases (
    case_id bigint PRIMARY KEY,
    case_number varchar(24) NOT NULL UNIQUE,
    customer_id bigint NOT NULL REFERENCES crm.customers(customer_id),
    contact_id bigint,
    case_type varchar(50) NOT NULL,
    priority varchar(20) NOT NULL,
    case_status varchar(30) NOT NULL,
    subject varchar(255) NOT NULL,
    description text,
    channel varchar(30) NOT NULL,
    assigned_team varchar(100) NOT NULL,
    opened_at timestamptz NOT NULL,
    first_response_at timestamptz,
    resolved_at timestamptz,
    satisfaction_score integer
);

CREATE TABLE IF NOT EXISTS crm.campaigns (
    campaign_id bigint PRIMARY KEY,
    campaign_name varchar(255) NOT NULL,
    campaign_type varchar(50) NOT NULL,
    campaign_status varchar(30) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    budget numeric(18,2) NOT NULL,
    expected_revenue numeric(18,2) NOT NULL,
    target_segment varchar(50) NOT NULL,
    owner varchar(150) NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS crm.campaign_members (
    campaign_member_id bigint PRIMARY KEY,
    campaign_id bigint NOT NULL REFERENCES crm.campaigns(campaign_id),
    customer_id bigint NOT NULL REFERENCES crm.customers(customer_id),
    member_status varchar(30) NOT NULL,
    responded_at timestamptz,
    response_channel varchar(30),
    converted boolean NOT NULL,
    attributed_revenue numeric(18,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contacts_customer ON crm.contacts(customer_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON crm.leads(lead_status);
CREATE INDEX IF NOT EXISTS idx_opportunities_customer ON crm.opportunities(customer_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_stage ON crm.opportunities(sales_stage);
CREATE INDEX IF NOT EXISTS idx_activities_customer_time ON crm.activities(customer_id, activity_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_customer ON crm.support_cases(customer_id);
CREATE INDEX IF NOT EXISTS idx_campaign_members_campaign ON crm.campaign_members(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_members_customer ON crm.campaign_members(customer_id);

CREATE OR REPLACE VIEW analytics.customer_360 AS
SELECT
    c.customer_id,
    c.customer_number,
    COALESCE(c.company_name, concat_ws(' ', c.first_name, c.last_name)) AS customer_name,
    c.customer_type,
    c.segment,
    c.industry,
    c.country,
    c.customer_status,
    count(DISTINCT ct.contact_id) AS contact_count,
    count(DISTINCT o.opportunity_id) AS opportunity_count,
    COALESCE(sum(DISTINCT o.amount) FILTER (WHERE o.sales_stage = 'Closed Won'), 0) AS won_revenue,
    count(DISTINCT sc.case_id) AS support_case_count,
    max(a.activity_at) AS last_activity_at
FROM crm.customers c
LEFT JOIN crm.contacts ct ON ct.customer_id = c.customer_id
LEFT JOIN crm.opportunities o ON o.customer_id = c.customer_id
LEFT JOIN crm.support_cases sc ON sc.customer_id = c.customer_id
LEFT JOIN crm.activities a ON a.customer_id = c.customer_id
GROUP BY c.customer_id;

CREATE OR REPLACE VIEW analytics.sales_pipeline AS
SELECT
    sales_stage,
    count(*) AS opportunity_count,
    sum(amount) AS pipeline_amount,
    sum(amount * probability_percent / 100.0) AS weighted_pipeline_amount,
    avg(probability_percent) AS average_probability
FROM crm.opportunities
GROUP BY sales_stage;

CREATE OR REPLACE VIEW analytics.campaign_performance AS
SELECT
    c.campaign_id,
    c.campaign_name,
    c.campaign_type,
    c.budget,
    count(cm.campaign_member_id) AS audience_size,
    count(*) FILTER (WHERE cm.responded_at IS NOT NULL) AS response_count,
    count(*) FILTER (WHERE cm.converted) AS conversion_count,
    sum(cm.attributed_revenue) AS attributed_revenue
FROM crm.campaigns c
LEFT JOIN crm.campaign_members cm ON cm.campaign_id = c.campaign_id
GROUP BY c.campaign_id;
"""

with conn.cursor() as cur:
    cur.execute(DDL)
    cur.execute("SELECT count(*) FROM crm.customers")
    existing_customers = cur.fetchone()[0]
conn.commit()

if existing_customers:
    print(
        f"CRM data already exists ({existing_customers:,} customers). "
        "No data was added. Use a new database or truncate the CRM schema for a clean reload."
    )
    conn.close()
    raise SystemExit(0)

now = datetime.now(timezone.utc)
owners = [
    "Olivia Carter", "Liam Bennett", "Emma Collins", "Noah Foster",
    "Ava Mitchell", "Ethan Parker", "Sophia Reed", "Mason Cooper",
    "Isabella Brooks", "Lucas Morgan", "Mia Richardson", "James Bailey",
]
industries = [
    "Technology", "Financial Services", "Healthcare", "Manufacturing",
    "Retail", "Telecommunications", "Professional Services", "Education",
    "Transportation", "Energy", "Hospitality", "Media",
]
segments = ["Enterprise", "Mid-Market", "Small Business", "Consumer", "Strategic"]
lead_sources = ["Website", "Referral", "Partner", "Webinar", "Conference", "Paid Search", "Organic Search", "Outbound"]


def copy_batches(table: str, columns: tuple[str, ...], total: int, row_factory) -> None:
    """Generate rows lazily and load them with COPY in committed batches."""
    if total == 0:
        print(f"{table}: skipped")
        return
    copy_sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    for start in range(1, total + 1, batch_size):
        end = min(start + batch_size - 1, total)
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as copy:
                for row_id in range(start, end + 1):
                    copy.write_row(row_factory(row_id))
        conn.commit()
        print(f"{table}: {end:,}/{total:,}", flush=True)


def random_timestamp(days_back: int = 1_825) -> datetime:
    return now - timedelta(seconds=random.randint(0, days_back * 86_400))


def customer_row(customer_id: int):
    is_b2b = random.random() < 0.68
    created_at = random_timestamp(3_650)
    updated_at = created_at + timedelta(seconds=random.randint(0, max(1, int((now - created_at).total_seconds()))))
    first_name = fake.first_name()
    last_name = fake.last_name()
    country = random.choice(["United States", "Canada", "United Kingdom", "Australia", "Singapore", "Germany"])
    return (
        customer_id,
        f"CUST-{customer_id:010d}",
        "Business" if is_b2b else "Individual",
        fake.company() if is_b2b else None,
        None if is_b2b else first_name,
        None if is_b2b else last_name,
        fake.unique.email(),
        fake.phone_number(),
        None if is_b2b else fake.date_of_birth(minimum_age=18, maximum_age=85),
        random.choice(industries) if is_b2b else None,
        random.choices(segments, weights=[12, 25, 28, 25, 10], k=1)[0],
        Decimal(str(round(random.uniform(100_000, 2_000_000_000), 2))) if is_b2b else None,
        random.randint(5, 50_000) if is_b2b else None,
        fake.street_address(), fake.city(), fake.state(), fake.postcode(), country,
        random.choice(["English", "Spanish", "French", "German"]),
        random.random() < 0.64,
        random.choices(["Active", "Inactive", "Prospect", "Churned"], weights=[72, 10, 12, 6], k=1)[0],
        random.choice(lead_sources), random.choice(owners), created_at, updated_at,
    )


copy_batches("crm.customers", (
    "customer_id", "customer_number", "customer_type", "company_name", "first_name", "last_name",
    "email", "phone", "date_of_birth", "industry", "segment", "annual_revenue", "employee_count",
    "address_line_1", "city", "state", "postal_code", "country", "preferred_language",
    "marketing_opt_in", "customer_status", "acquisition_source", "assigned_owner", "created_at", "updated_at",
), customer_count, customer_row)


def contact_row(contact_id: int):
    created_at = random_timestamp(2_500)
    return (
        contact_id, random.randint(1, customer_count), fake.first_name(), fake.last_name(),
        fake.job(), random.choice(["Sales", "Marketing", "Finance", "Operations", "IT", "Procurement", "Executive"]),
        fake.company_email(), fake.email() if random.random() < 0.25 else None,
        fake.phone_number(), fake.phone_number() if random.random() < 0.7 else None,
        random.random() < 0.35, random.choices(["Active", "Inactive", "Do Not Contact"], [88, 8, 4], k=1)[0],
        random.choice(["Email", "Phone", "SMS", "LinkedIn"]), random.random() < 0.72, random.random() < 0.41,
        created_at, created_at + timedelta(days=random.randint(0, 500)),
    )


copy_batches("crm.contacts", (
    "contact_id", "customer_id", "first_name", "last_name", "job_title", "department",
    "business_email", "personal_email", "mobile_phone", "office_phone", "is_primary", "contact_status",
    "preferred_channel", "consent_email", "consent_sms", "created_at", "updated_at",
), contact_count, contact_row)


def lead_row(lead_id: int):
    created_at = random_timestamp(2_000)
    status = random.choices(["New", "Working", "Qualified", "Converted", "Disqualified"], [20, 25, 20, 25, 10], k=1)[0]
    return (
        lead_id, f"LEAD-{lead_id:010d}", fake.first_name(), fake.last_name(), fake.company(),
        fake.unique.email(), fake.phone_number(), fake.job(), random.choice(lead_sources), status,
        random.randint(0, 100), Decimal(str(round(random.uniform(1_000, 5_000_000), 2))),
        random.choice(industries), random.choice(["United States", "Canada", "United Kingdom", "Australia", "Singapore"]),
        random.choice(owners), created_at,
        created_at + timedelta(days=random.randint(1, 180)) if status == "Converted" else None,
    )


copy_batches("crm.leads", (
    "lead_id", "lead_number", "first_name", "last_name", "company_name", "email", "phone", "job_title",
    "lead_source", "lead_status", "lead_score", "estimated_value", "industry", "country", "assigned_owner",
    "created_at", "converted_at",
), lead_count, lead_row)


def opportunity_row(opportunity_id: int):
    stage = random.choices(
        ["Prospecting", "Qualification", "Needs Analysis", "Proposal", "Negotiation", "Closed Won", "Closed Lost"],
        [12, 15, 14, 14, 12, 22, 11], k=1,
    )[0]
    probability = {"Prospecting": 10, "Qualification": 20, "Needs Analysis": 40, "Proposal": 60, "Negotiation": 80, "Closed Won": 100, "Closed Lost": 0}[stage]
    created_at = random_timestamp(1_500)
    expected = (created_at + timedelta(days=random.randint(15, 240))).date()
    actual = expected if stage.startswith("Closed") else None
    return (
        opportunity_id, f"OPP-{opportunity_id:010d}", random.randint(1, customer_count),
        f"{fake.bs().title()} Opportunity", stage, Decimal(str(round(random.uniform(5_000, 25_000_000), 2))),
        min(100, max(0, probability + random.randint(-5, 5))), expected, actual,
        random.choice(["Price", "Competition", "No Budget", "Timing", "No Decision"]) if stage == "Closed Lost" else None,
        random.choice(lead_sources), random.choice(owners), created_at,
        created_at + timedelta(days=random.randint(0, 300)),
    )


copy_batches("crm.opportunities", (
    "opportunity_id", "opportunity_number", "customer_id", "opportunity_name", "sales_stage", "amount",
    "probability_percent", "expected_close_date", "actual_close_date", "loss_reason", "lead_source",
    "assigned_owner", "created_at", "updated_at",
), opportunity_count, opportunity_row)

activity_types = ["Call", "Email", "Meeting", "Demo", "Task", "Note"]

def activity_row(activity_id: int):
    activity_type = random.choice(activity_types)
    return (
        activity_id, random.randint(1, customer_count),
        random.randint(1, contact_count) if contact_count and random.random() < 0.75 else None,
        random.randint(1, opportunity_count) if opportunity_count and random.random() < 0.45 else None,
        activity_type, f"{activity_type}: {fake.sentence(nb_words=6)}",
        random.choice(["Completed", "Scheduled", "Cancelled", "In Progress"]),
        random.choice(["Email", "Phone", "Video", "In Person", "Web"]), random_timestamp(1_000),
        random.randint(5, 180) if activity_type in {"Call", "Meeting", "Demo"} else None,
        random.choice(["Positive", "Neutral", "Follow-up Required", "No Response", "Resolved"]),
        random.choice(owners), fake.sentence(nb_words=12) if random.random() < 0.35 else None,
    )


copy_batches("crm.activities", (
    "activity_id", "customer_id", "contact_id", "opportunity_id", "activity_type", "activity_subject",
    "activity_status", "channel", "activity_at", "duration_minutes", "outcome", "performed_by", "notes",
), activity_count, activity_row)


def support_case_row(case_id: int):
    opened = random_timestamp(1_200)
    status = random.choices(["New", "In Progress", "Waiting on Customer", "Resolved", "Closed"], [10, 22, 12, 28, 28], k=1)[0]
    response = opened + timedelta(minutes=random.randint(5, 2_880))
    resolved = response + timedelta(hours=random.randint(1, 240)) if status in {"Resolved", "Closed"} else None
    return (
        case_id, f"CASE-{case_id:010d}", random.randint(1, customer_count),
        random.randint(1, contact_count) if contact_count and random.random() < 0.8 else None,
        random.choice(["Product Issue", "Billing", "Technical Support", "Account Access", "Feature Request"]),
        random.choices(["Low", "Medium", "High", "Critical"], [28, 45, 22, 5], k=1)[0], status,
        fake.sentence(nb_words=8), fake.paragraph(nb_sentences=3),
        random.choice(["Email", "Phone", "Portal", "Chat"]),
        random.choice(["Tier 1 Support", "Tier 2 Support", "Customer Success", "Billing Operations"]),
        opened, response, resolved, random.randint(1, 5) if resolved else None,
    )


copy_batches("crm.support_cases", (
    "case_id", "case_number", "customer_id", "contact_id", "case_type", "priority", "case_status",
    "subject", "description", "channel", "assigned_team", "opened_at", "first_response_at", "resolved_at",
    "satisfaction_score",
), support_case_count, support_case_row)


def campaign_row(campaign_id: int):
    start = fake.date_between(start_date="-3y", end_date="+90d")
    end = start + timedelta(days=random.randint(15, 180))
    budget = Decimal(str(round(random.uniform(5_000, 2_000_000), 2)))
    return (
        campaign_id, f"{start.year} {fake.catch_phrase()} Campaign",
        random.choice(["Email", "Webinar", "Conference", "Digital Advertising", "Partner", "Direct Mail"]),
        random.choice(["Planned", "Active", "Completed", "Cancelled"]), start, end, budget,
        budget * Decimal(str(round(random.uniform(1.2, 8.0), 2))), random.choice(segments),
        random.choice(owners), random_timestamp(1_500),
    )


copy_batches("crm.campaigns", (
    "campaign_id", "campaign_name", "campaign_type", "campaign_status", "start_date", "end_date",
    "budget", "expected_revenue", "target_segment", "owner", "created_at",
), campaign_count, campaign_row)


def campaign_member_row(member_id: int):
    responded = random.random() < 0.22
    converted = responded and random.random() < 0.16
    return (
        member_id, random.randint(1, campaign_count), random.randint(1, customer_count),
        random.choice(["Sent", "Delivered", "Opened", "Clicked", "Responded", "Unsubscribed"]),
        random_timestamp(1_000) if responded else None,
        random.choice(["Email", "Web", "Phone", "Event"]) if responded else None,
        converted, Decimal(str(round(random.uniform(500, 250_000), 2))) if converted else Decimal("0.00"),
    )


copy_batches("crm.campaign_members", (
    "campaign_member_id", "campaign_id", "customer_id", "member_status", "responded_at",
    "response_channel", "converted", "attributed_revenue",
), campaign_member_count, campaign_member_row)

with conn.cursor() as cur:
    quoted_role = '"' + trino_user.replace('"', '""') + '"'
    cur.execute(f"GRANT USAGE ON SCHEMA crm, analytics TO {quoted_role}")
    cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA crm, analytics TO {quoted_role}")
    cur.execute("ANALYZE crm.customers")
    cur.execute("ANALYZE crm.contacts")
    cur.execute("ANALYZE crm.leads")
    cur.execute("ANALYZE crm.opportunities")
    cur.execute("ANALYZE crm.activities")
    cur.execute("ANALYZE crm.support_cases")
    cur.execute("ANALYZE crm.campaigns")
    cur.execute("ANALYZE crm.campaign_members")
conn.commit()
conn.close()

print("English CRM dataset generation completed successfully.")
