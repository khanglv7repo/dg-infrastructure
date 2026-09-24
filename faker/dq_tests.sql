-- Verification queries for the six Data Quality dimensions.
-- Each query should return DQ_ISSUES_PER_DIMENSION rows after generate_dq.py runs.

-- 1) Completeness: required customer name is missing.
SELECT record_id
FROM dq_lab.customer_profile
WHERE full_name IS NULL OR btrim(full_name) = '';

-- 2) Accuracy: observed value differs from authoritative reference.
SELECT p.record_id
FROM dq_lab.customer_profile p
JOIN dq_lab.customer_reference r ON r.reference_id = p.reference_id
WHERE p.annual_income IS DISTINCT FROM r.annual_income;

-- 3) Uniqueness: customer business key is duplicated.
SELECT p.record_id
FROM dq_lab.customer_profile p
JOIN (
    SELECT customer_number
    FROM dq_lab.customer_profile
    GROUP BY customer_number
    HAVING count(*) > 1
) d ON d.customer_number = p.customer_number;

-- 4) Consistency: country code and name disagree.
SELECT p.record_id
FROM dq_lab.customer_profile p
LEFT JOIN dq_lab.country_reference c ON c.country_code = p.country_code
WHERE c.country_code IS NULL OR c.country_name IS DISTINCT FROM p.country_name;

-- 5) Validity: malformed email.
SELECT record_id
FROM dq_lab.customer_profile
WHERE email IS NULL
   OR email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$';

-- 6) Timeliness: source row is older than the 30-day SLA.
SELECT record_id
FROM dq_lab.customer_profile
WHERE source_updated_at IS NULL
   OR source_updated_at < now() - interval '30 days';

-- Ground-truth cross-check. Every row should show counts_match = true.
SELECT *
FROM dq_lab.quality_validation
ORDER BY dimension;
