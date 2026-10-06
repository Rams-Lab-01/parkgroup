\echo '===== contract level: paid vs balance ====='
WITH c AS (
  SELECT sc.id, sc.sale_price, coalesce(sc.total_paid,0) tp, sc.contract_date,
         (SELECT max(i.payment_date) FROM sale_contract_installment i
           WHERE i.contract_id=sc.id AND i.state='paid') AS last_pay
  FROM sale_contract sc
)
SELECT
  count(*) AS contracts,
  count(*) FILTER (WHERE sale_price - tp <= 0.01) AS zero_balance,
  count(*) FILTER (WHERE sale_price - tp > 0.01) AS with_balance,
  count(*) FILTER (WHERE last_pay IS NULL) AS never_paid,
  count(*) FILTER (WHERE contract_date IS NULL) AS no_contract_date,
  round(sum(sale_price - tp) FILTER (WHERE sale_price - tp > 0.01)) AS balance_sum
FROM c;

\echo '===== aging buckets (last payment, fallback contract date) ====='
WITH c AS (
  SELECT sc.id, sc.sale_price, coalesce(sc.total_paid,0) tp, sc.contract_date,
         (SELECT max(i.payment_date) FROM sale_contract_installment i
           WHERE i.contract_id=sc.id AND i.state='paid') AS last_pay
  FROM sale_contract sc
), a AS (
  SELECT *,
    CASE WHEN sale_price - tp <= 0.01 THEN NULL
         WHEN last_pay IS NOT NULL THEN CURRENT_DATE - last_pay
         WHEN contract_date IS NOT NULL THEN CURRENT_DATE - contract_date
         ELSE NULL END AS aging
  FROM c
)
SELECT bucket, count(*) AS units, round(sum(bal)) AS amount FROM (
  SELECT CASE
    WHEN aging BETWEEN 0 AND 30 THEN '0-30'
    WHEN aging BETWEEN 31 AND 60 THEN '31-60'
    WHEN aging BETWEEN 61 AND 90 THEN '61-90'
    WHEN aging BETWEEN 91 AND 180 THEN '91-180'
    WHEN aging > 180 THEN '180+'
    ELSE 'NO_AGING' END AS bucket,
    sale_price - tp AS bal
  FROM a
) t GROUP BY bucket ORDER BY bucket;

\echo '===== escrow classification counts ====='
SELECT
  count(*) FILTER (WHERE NOT has_source_data) AS no_source,
  count(*) FILTER (WHERE has_source_data AND abs(variance_amount) <= 0.01) AS reconciled,
  count(*) FILTER (WHERE has_source_data AND variance_amount < -0.01) AS under,
  count(*) FILTER (WHERE has_source_data AND variance_amount > 0.01) AS over,
  count(*) FILTER (WHERE escrow_pct = 0 OR escrow_pct IS NULL) AS no_pct
FROM escrow_allocation;

\echo '===== escrow: required missing vs allocated missing ====='
SELECT
  count(*) FILTER (WHERE COALESCE(required_amount,0) = 0) AS req_zero,
  count(*) FILTER (WHERE allocated_amount IS NULL) AS alloc_null,
  count(*) FILTER (WHERE allocated_amount = 0) AS alloc_zero,
  count(*) FILTER (WHERE required_amount IS NOT NULL) AS req_notnull
FROM escrow_allocation;

\echo '===== commission data ====='
SELECT count(*) AS commission_lines, round(sum(amount)) FROM commission_line;

\echo '===== property_details per project ====='
SELECT p.code, d.state, count(*), round(sum(d.sale_price)) 
FROM property_details d LEFT JOIN property_project p ON p.id=d.project_id
GROUP BY 1,2 ORDER BY 1,2;

\echo '===== units with no project ====='
SELECT count(*) FROM property_details WHERE project_id IS NULL;

\echo '===== contract_date range ====='
SELECT min(contract_date), max(contract_date), count(*) FILTER (WHERE contract_date IS NOT NULL) FROM sale_contract;

\echo '===== installment percentage distribution ====='
SELECT percentage, state, count(*) FROM sale_contract_installment GROUP BY 1,2 ORDER BY 1,2;
