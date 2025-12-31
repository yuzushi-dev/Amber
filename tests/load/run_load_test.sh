#!/bin/bash

# Activate virtual environment
source .venv/bin/activate

# Install locust if not installed
if ! command -v locust &> /dev/null; then
    echo "Locust could not be found. Installing..."
    pip install locust
fi

# Create a results directory
mkdir -p tests/load/results

echo "Starting Load Test with 50 Users..."

# Run locust in headless mode
locust -f tests/load/locustfile.py \
    --headless \
    -u 50 \
    -r 5 \
    --run-time 1m \
    --host http://localhost:8000 \
    --csv tests/load/results/load_test_results \
    --html tests/load/results/report.html

echo "Load test completed. Results saved in tests/load/results/"
