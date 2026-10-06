import ast

p = 'property_details.py'
src = open(p, encoding='utf-8', errors='replace').read()
tree = ast.parse(src)

# Find the get_development_kpis function
fn = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'get_development_kpis':
        fn = node
        break

print('found get_development_kpis at line', fn.lineno)

# Report every env[...] model referenced and every string domain leaf
for node in ast.walk(fn):
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
        pass

# Collect self.env['x'] model names
models = set()
for node in ast.walk(fn):
    if (isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == 'env'
            and isinstance(node.slice, ast.Constant)):
        models.add(node.slice.value)
print('\nmodels referenced:', sorted(models))

# Collect string literals that look like field names used in domains
fields = set()
for node in ast.walk(fn):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if v in ('project_id', 'company_id', 'state', 'sale_price', 'total_paid',
                 'admin_fee', 'required_amount', 'allocated_amount',
                 'variance_amount', 'has_source_data', 'property_id',
                 'contract_id', 'unit_type', 'amount', 'payment_date'):
            fields.add(v)
print('\ndomain field names used:', sorted(fields))