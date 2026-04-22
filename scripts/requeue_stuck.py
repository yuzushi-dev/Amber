from src.workers.tasks import process_document


def main():
    for doc_id in ['doc_68bf8f02572fb979', 'doc_b580d086e49120db', 'doc_fe80d5e62f9c97a7']:
        print(f"Queueing {doc_id}...")
        process_document.delay(doc_id, "default")

if __name__ == "__main__":
    main()
