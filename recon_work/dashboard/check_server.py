import sys
import xml.dom.minidom

ok = True
for p in sys.argv[1:]:
    try:
        xml.dom.minidom.parse(p)
        print('XML OK  ', p.split('/')[-1])
    except Exception as e:
        ok = False
        print('XML FAIL', p.split('/')[-1], e)

# also sanity check the JS is structurally sound
js = open(sys.argv[4], encoding='utf-8', errors='replace').read()
checks = {
    'single registration': js.count('dashboardActions.add') == 1,
    'single watchlist'   : js.count('this.state.watchlist =') == 1,
    'single cards build' : js.count('this.state.cards =') == 1,
    'no hardcoded cards' : 'value:"' not in js,
    'formatPct present'  : 'formatPct(v)' in js,
    'project_rows'       : 'this.state.project_rows' in js,
    'renderMap called'   : 'this.renderMap();' in js,
}
for k, v in checks.items():
    print(('PASS  ' if v else 'FAIL  ') + k)
    if not v:
        ok = False

print('ALL_OK' if ok else 'PROBLEMS_FOUND')