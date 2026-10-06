\echo '===== escrow_allocation columns ====='
SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='escrow_allocation';

\echo '===== sale_contract states ====='
SELECT state, overall_payment_state, count(*), round(sum(sale_price)) AS price_sum, round(sum(total_paid)) AS paid_sum
FROM sale_contract GROUP BY state, overall_payment_state ORDER BY 3 DESC;

\echo '===== installments by state ====='
SELECT state, count(*), round(sum(amount)) AS amt, count(due_date) due_dates, count(payment_date) pay_dates
FROM sale_contract_installment GROUP BY state ORDER BY 2 DESC;

\echo '===== overdue nonpaid installments ====='
SELECT count(*) AS cnt, round(sum(amount)) AS amt
FROM sale_contract_installment WHERE due_date < CURRENT_DATE AND payment_date IS NULL;

\echo '===== property_details states ====='
SELECT state, count(*) FROM property_details GROUP BY 1 ORDER BY 2 DESC;

\echo '===== property_details type ====='
SELECT property_type::text, count(*) FROM property_details GROUP BY 1 ORDER BY 2 DESC;

\echo '===== property_project ====='
SELECT id, code, state, region_id FROM property_project ORDER BY code;

\echo '===== region tables ====='
SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%region%';

\echo '===== property_project columns ====='
SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='property_project';

\echo '===== companies ====='
SELECT id, name FROM res_company ORDER BY id;

\echo '===== escrow project link ====='
SELECT company_id, count(*) FROM sale_contract GROUP BY 1;
