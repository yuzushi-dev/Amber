import fitz

filename = "Backup not Running after upgrade to Carbonio 25.6.0   Howto fix   Zextras Group.pdf"
print(f"Opening {filename}...")

try:
    doc = fitz.open(filename)
    print(f"Page count: {doc.page_count}")
    print(f"Metadata: {doc.metadata}")

    print("\n--- Page 1 Text ---")
    text = doc[0].get_text()
    print(text[:500])

    print("\n--- Searching for keywords ---")
    full_text = ""
    for page in doc:
        full_text += page.get_text()

    keywords = ["backup", "consul", "bootstrap", "database", "db"]
    for kw in keywords:
        count = full_text.lower().count(kw)
        print(f"Keyword '{kw}': found {count} times")

    if "backup" in full_text.lower():
        print("\n--- Backup Context ---")
        idx = full_text.lower().find("backup")
        print(full_text[max(0, idx - 100) : idx + 100])
    else:
        print("\n'backup' not found in text.")

except Exception as e:
    print(f"Error: {e}")
