
def get_type_color_id(type_str):
    hash_val = 0
    for i in range(len(type_str)):
        char = ord(type_str[i])
        hash_val = ((hash_val << 5) - hash_val) + char
        hash_val = hash_val & hash_val # 32bit integer simulation
    return abs(hash_val)

COMMUNITY_COLORS_LEN = 8
# Colors:
# 0: Amber
# 1: Orange
# 2: Cyan
# 3: Violet
# 4: Emerald
# 5: Blue
# 6: Pink
# 7: Red

types = ['CLASS_OF_SERVICE', 'ITEM', 'CONFIG_OPTION', 'Organization', 'Action', 'SERVICE', 'CONCEPT', 'DATE', 'TIME', 'LOCATION', 'Image Format', 'FEATURE', 'TASK', 'ACCOUNT', 'RESOURCE', 'PROCEDURE', 'Feature', 'ROLE', 'COMPONENT', 'File Format', 'PERSON', 'DOCUMENT', 'GROUP', 'Link', 'CLI_COMMAND', 'Address Book', 'EVENT', 'Product', 'Folder', 'DOMAIN', 'Concept']

print(f"{'TYPE':<20} | {'HASH':<10} | {'INDEX':<5} | {'COLOR'}")
print("-" * 50)

for t in types:
    h = get_type_color_id(t)
    idx = abs(h) % COMMUNITY_COLORS_LEN

    color = "UNKNOWN"
    if idx == 0: color = "Amber"
    elif idx == 1: color = "Orange"
    elif idx == 2: color = "Cyan"
    elif idx == 3: color = "VIOLET (PURPLE)"
    elif idx == 4: color = "Emerald"
    elif idx == 5: color = "Blue"
    elif idx == 6: color = "Pink"
    elif idx == 7: color = "Red"

    print(f"{t:<20} | {h:<10} | {idx:<5} | {color}")
