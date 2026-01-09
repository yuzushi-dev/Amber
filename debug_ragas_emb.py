
try:
    import ragas.embeddings
    print("ragas.embeddings:", dir(ragas.embeddings))
    from ragas.metrics import ResponseRelevancy
    import inspect
    print("ResponseRelevancy init:", inspect.signature(ResponseRelevancy.__init__))
    import inspect
    from ragas.embeddings import OpenAIEmbeddings
    print("OpenAIEmbeddings init:", inspect.signature(OpenAIEmbeddings.__init__))
except ImportError:
    print("ragas not installed")
except Exception as e:
    print(e)
