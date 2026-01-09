
import inspect
try:
    from ragas.metrics import Faithfulness
    import ragas.metrics
    # Try to find where single_turn_ascore is defined
    print("Faithfulness mro:", Faithfulness.mro())
    print("Sig:", inspect.signature(Faithfulness.single_turn_ascore))
except ImportError:
    print("Ragas not installed")
except Exception as e:
    print("Error:", e)
