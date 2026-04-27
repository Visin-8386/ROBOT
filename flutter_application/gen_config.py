"""
Đọc D:\\ROBOT\\shared_config.h → sinh lib/shared_config.dart
Chạy trước khi build Flutter:
    python gen_config.py
"""

import re, pathlib, sys

HEADER = pathlib.Path(__file__).resolve().parent.parent / "shared_config.h"
OUTPUT = pathlib.Path(__file__).resolve().parent / "lib" / "shared_config.dart"

DEFINES_TO_EXTRACT = {
    "SERVER_IP":   ("serverIp",   "String"),
    "WIFI_SSID":   ("wifiSsid",   "String"),
    "WIFI_PASS":   ("wifiPass",   "String"),
}
INT_DEFINES = {
    "WIFI_MAX_RETRY": ("wifiMaxRetry", "int"),
}

def parse_header(path: pathlib.Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'#define\s+(\w+)\s+"([^"]*)"', line)
        if m:
            values[m.group(1)] = ("str", m.group(2))
            continue
        m = re.match(r'#define\s+(\w+)\s+(\d+)', line)
        if m:
            values[m.group(1)] = ("int", int(m.group(2)))
    return values

def generate_dart(values: dict) -> str:
    lines = [
        "// AUTO-GENERATED from shared_config.h — KHÔNG SỬA TAY",
        "// Chạy:  python gen_config.py",
        "",
        "class SharedConfig {",
    ]
    for define, (dart_name, dart_type) in DEFINES_TO_EXTRACT.items():
        if define in values:
            _, val = values[define]
            lines.append(f"  static const {dart_type} {dart_name} = '{val}';")
    for define, (dart_name, dart_type) in INT_DEFINES.items():
        if define in values:
            _, val = values[define]
            lines.append(f"  static const {dart_type} {dart_name} = {val};")

    # Port mặc định (không có trong .h, nhưng server luôn chạy port 8000)
    lines.append("  static const int serverPort = 8000;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)

def main():
    if not HEADER.exists():
        print(f"ERROR: Không tìm thấy {HEADER}")
        sys.exit(1)

    values = parse_header(HEADER)
    dart = generate_dart(values)
    OUTPUT.write_text(dart, encoding="utf-8")
    print(f"OK  {HEADER.name}  →  {OUTPUT}")
    for define in list(DEFINES_TO_EXTRACT) + list(INT_DEFINES):
        if define in values:
            print(f"     {define} = {values[define][1]}")

if __name__ == "__main__":
    main()
