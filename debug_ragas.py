
try:
    from ragas.metrics import Faithfulness
    print("Faithfulness methods:", [m for m in dir(Faithfulness) if not m.startswith("_")])
except ImportError:
    print("Ragas not installed")
