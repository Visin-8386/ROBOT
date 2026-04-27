import os, io

def fix_sdkconfig():
    filepath = 'sdkconfig'
    old_filepath = 'sdkconfig.old'
    
    # Try reading from sdkconfig.old as it was unmodified by the echo commands
    try:
        with open(old_filepath, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        with open(filepath, 'rb') as f:
            data = f.read()

    # Try decoding as utf-16 if needed, otherwise utf-8
    decoded = ''
    if b'\x00' in data:
        # Strip null bytes in case it's a messed up mix of utf-8 and utf-16
        decoded = data.replace(b'\x00', b'').decode('utf-8', errors='ignore')
    else:
        decoded = data.decode('utf-8', errors='ignore')

    lines = decoded.splitlines()
    
    # Clean up any existing brownout configs
    new_lines = []
    for line in lines:
        if 'CONFIG_ESP_BROWNOUT_DET' not in line:
            new_lines.append(line)

    # Append the correct disabled setting
    new_lines.append('CONFIG_ESP_BROWNOUT_DET=n')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines) + '\n')
        
    print("Fixed sdkconfig successfully.")

if __name__ == "__main__":
    fix_sdkconfig()
