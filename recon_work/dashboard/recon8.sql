SELECT d.unit_number, i.id, i.sequence, i.name, i.state, i.due_date, i.payment_date, i.amount, i.percentage, i.invoice_id
FROM sale_contract_installment i
JOIN sale_contract sc ON sc.id = i.contract_id
JOIN property_details d ON d.id = sc.property_id
JOIN property_project p ON p.id = d.project_id
WHERE p.code='BR1' AND d.unit_number IN ('109','206','208')
ORDER BY d.unit_number, i.sequence;
