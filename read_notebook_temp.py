import json
nb = json.load(open(r'D:\ROBOT\notebooked4c917f13.ipynb', encoding='utf-8'))
for i, c in enumerate(nb['cells']):
    if c['cell_type'] == 'code':
        print(f'---CELL {i} ---\n')
        print(''.join(c['source']))
