import sys

def p(*a):
    print(*a)
    sys.stdout.flush()

model = env['property.details'].sudo()
payload = model.get_development_kpis()

def show(k):
    v = payload.get(k)
    return round(v, 2) if isinstance(v, float) else v

p("=" * 62)
p("INVENTORY & SALES")
for k in ['total_units', 'sold_units', 'available_units', 'sell_through_pct',
          'sales_value', 'avg_psf_sold']:
    p(f"  {k:22} = {show(k)}")

p("")
p("UNIT MIX")
p("  labels:", payload.get('unit_mix_labels'))
p("  values:", payload.get('unit_mix_values'))

p("")
p("AGING BUCKETS (real, from last activity date)")
for b in payload.get('aging_buckets') or []:
    p(f"  {b['label']:14} count={b['count']:4}  amount={round(b.get('amount',0),2):,.2f}")
p(f"  undated balance (cannot age): {round(payload.get('undated_balance',0),2):,.2f}")

p("")
p("COLLECTIONS & RECEIVABLES")
for k in ['collected', 'balance_due', 'collection_pct', 'dso_days',
          'aged_overdue_units', 'aged_overdue_amount', 'admin_fees_total']:
    p(f"  {k:22} = {show(k)}")

p("")
p("ESCROW COMPLIANCE")
for k in ['required_escrow', 'allocated_escrow', 'escrow_shortfall',
          'funded_pct', 'recon_rate', 'missing_source_count']:
    p(f"  {k:22} = {show(k)}")

p("")
p("PER-PROJECT")
for code, rec in (payload.get('per_project') or {}).items():
    p(f"  {code}: units={rec.get('units')} sold={rec.get('sold')} "
      f"sell%={round(rec.get('sell_pct',0),1)} "
      f"sales={round(rec.get('sales_value',0),2):,.0f} "
      f"collected={round(rec.get('collected',0),2):,.0f} "
      f"req={round(rec.get('required_escrow',0),2):,.0f} "
      f"alloc={round(rec.get('allocated_escrow',0),2):,.0f} "
      f"var={round(rec.get('variance',0),2):,.0f} "
      f"recon%={round(rec.get('recon_rate',0),1)} "
      f"funded%={round(rec.get('funded_pct',0),1)}")

p("")
p("PROJECT MAP (map pins)")
for code, rec in (payload.get('project_map') or {}).items():
    p(f"  {code}: name={rec.get('name')!r} lat={rec.get('lat')} "
      f"lon={rec.get('lon')} sold={rec.get('count')}")

env.cr.rollback()
p("")
p("=" * 62)
p("DONE (rolled back - read only)")