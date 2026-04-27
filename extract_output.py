import json

with open(r'D:\ROBOT\notebooked4c917f13.ipynb', encoding='utf-8') as f:
    nb = json.load(f)
    
for i, c in enumerate(nb['cells']):
    if c['cell_type'] == 'code':
        print('---CELL', i, '---')
        print(''.join(c['source']))
