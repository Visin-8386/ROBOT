import json

# Open and load the notebook
with open(r'D:\ROBOT\notebooks\notebooked4c917f13.ipynb', encoding='utf-8') as f:
    nb = json.load(f)

# Extract and print all code cells
for i, cell in enumerate(nb['cells']):
    if cell['cell_type'] == 'code':
        source = ''.join(cell['source'])
        print(f'---CELL {i} ---\n{source}')
