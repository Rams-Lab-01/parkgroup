#!/bin/bash
Q(){ docker exec sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -At -c "$1"; }
echo "== escrow actions in parkgroup =="
Q "select module||'.'||name from ir_model_data where module='sgc_escrow' and model='ir.actions.act_window';"
echo "== escrow.allocation views in parkgroup =="
Q "select count(*), string_agg(distinct type, ',') from ir_ui_view where model='escrow.allocation';"
echo "== escrow menus in parkgroup =="
Q "select name from ir_ui_menu where id in (select res_id from ir_model_data where module='sgc_escrow' and model='ir.ui.menu');"
echo "== escrow module version on disk =="
grep -m1 "version" /opt/odoo/deploy/sgc-rent-mt/addons/sgc_escrow/__manifest__.py
echo "== escrow reconciled field (deployed code) =="
grep -n "reconciled" /opt/odoo/deploy/sgc-rent-mt/addons/sgc_escrow/models/escrow_allocation.py | head -25
echo "== offplan action/menu for dashboard =="
Q "select module||'.'||name from ir_model_data where model='ir.actions.client' and module='sgc_offplan_rental_property_management';"
echo "== dashboard menu =="
Q "select m.id, m.name->>'en_US' is null, coalesce(m.name->>'en_US', m.name) from ir_ui_menu m where m.id in (select res_id from ir_model_data where name like '%dashboard%' and module like 'sgc_offplan%');"
echo "== installment action id =="
Q "select module||'.'||name||' = '||res_id from ir_model_data where model='ir.actions.act_window' and name like '%installment%';"
echo "== property.details list action =="
Q "select module||'.'||name||' = '||res_id from ir_model_data where model='ir.actions.act_window' and res_id in (select id from ir_actions_act_window where res_model='property.details') limit 10;"
