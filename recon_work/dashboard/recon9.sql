WITH c AS (
  SELECT sc.id, sc.sale_price, coalesce(sc.total_paid,0) tp, sc.contract_date,
    (SELECT max(i.payment_date) FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid') last_pay,
    (SELECT count(*) FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid' AND i.percentage IN (10,20)) milestone_paid
  FROM sale_contract sc
)
SELECT
  count(*) FILTER (WHERE last_pay IS NOT NULL AND sale_price-tp > 0.01) AS var_a_cnt,
  round(sum(sale_price-tp) FILTER (WHERE last_pay IS NOT NULL AND sale_price-tp > 0.01)) AS var_a_amt,
  count(*) FILTER (WHERE (last_pay IS NOT NULL OR milestone_paid > 0) AND sale_price-tp > 0.01) AS var_c_cnt,
  round(sum(sale_price-tp) FILTER (WHERE (last_pay IS NOT NULL OR milestone_paid > 0) AND sale_price-tp > 0.01)) AS var_c_amt,
  count(*) FILTER (WHERE sale_price-tp > 0.01) AS all_bal_cnt,
  round(sum(sale_price-tp) FILTER (WHERE sale_price-tp > 0.01)) AS all_bal_amt
FROM c;
