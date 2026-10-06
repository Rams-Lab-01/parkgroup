SELECT d.unit_number, sc.id, sc.contract_date, sc.sale_price, sc.total_paid,
 (SELECT max(i.payment_date) FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid') last_pay,
 (SELECT max(i.write_date)::date FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid') last_w,
 (SELECT max(i.create_date)::date FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid') last_c,
 (SELECT count(*) FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid' AND i.payment_date IS NULL) paid_no_pdate
FROM sale_contract sc
JOIN property_details d ON d.id=sc.property_id
JOIN property_project p ON p.id=d.project_id
WHERE p.code='BR1' AND d.unit_number IN ('101','102','106','108','201','206','208','212')
ORDER BY d.unit_number;
