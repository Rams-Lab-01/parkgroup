p = 'property_project_views.xml'
s = open(p, encoding='utf-8', errors='replace').read()

old = '''<group string="Location">
                         <field name="address" placeholder="Street / landmark"/>
                         <field name="city"/>
                         <field name="state_id"/>
                         <field name="country_id"/>
                         <field name="zip"/>
                     </group>'''

new = '''<group string="Location">
                         <field name="address" placeholder="Street / landmark"/>
                         <field name="city"/>
                         <field name="state_id"/>
                         <field name="country_id"/>
                         <field name="zip"/>
                         <field name="geo_latitude" placeholder="e.g. 25.8090"/>
                         <field name="geo_longitude" placeholder="e.g. 55.9420"/>
                     </group>'''

lines = s.split('\n')
# first Location group is the form view (line 153); only patch that one
count = s.count(old)
print('matching Location groups:', count)

idx = s.find(old)
if idx == -1:
    raise SystemExit('form Location group not found')

s = s[:idx] + new + s[idx + len(old):]

open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched form Location group only')

# verify
print('geo_latitude occurrences now:', s.count('geo_latitude'))