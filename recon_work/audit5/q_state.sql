\d sale_contract_installment
---BLOCKED---
select pr.code proj, d.id, d.unit_number, d.state unit_state, c.id cid, c.state c_state, p.name buyer, p.phone, p.email, c.sale_price, c.total_paid, c.overall_payment_state from property_details d join property_project pr on pr.id=d.project_id left join sale_contract c on c.property_id=d.id left join res_partner p on p.id=c.buyer_id where (pr.code='BR2' and d.unit_number in ('212','705','709','104')) or (pr.code='BR1' and d.unit_number='408') order by 1,2
---STATE-DIST---
select pr.code, d.state, count(*) from property_details d join property_project pr on pr.id=d.project_id group by 1,2 order by 1,2
---TOTALS---
select count(*) units, count(*) filter (where d.state='sold') sold from property_details d where d.active
select count(*) contracts, sum(total_paid) total_paid from sale_contract c where c.state not in ('draft','cancel')
select count(*) from sale_contract_installment i join sale_contract c on c.id=i.contract_id where i.state='paid'
select coalesce(sum(amount),0) from sale_contract_installment i join sale_contract c on c.id=i.contract_id where i.state='paid'
