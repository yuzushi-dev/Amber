import time

from locust import HttpUser, between, events, task


class ChatUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        """Authenticate and set headers."""
        self.headers = {
            "X-API-Key": "amber-dev-key-2024",
            "Content-Type": "application/json"
        }

    @task(3)
    def query_stream(self):
        """Simulate a streaming query."""
        payload = {
            "query": "What is the summary of the latest document?",
            "options": {
                "stream": True,
                "include_trace": False
            }
        }

        start_time = time.time()
        # Note: server-sent events might need special handling, but basic POST to /stream works
        with self.client.post("/v1/query/stream", json=payload, headers=self.headers, catch_response=True, stream=True) as response:
            if response.status_code == 200:
                first_token_received = False
                for line in response.iter_lines():
                    if line:
                        if not first_token_received:
                            ttft = (time.time() - start_time) * 1000
                            events.request.fire(
                                request_type="POST",
                                name="Time To First Token",
                                response_time=ttft,
                                response_length=0,
                            )
                            first_token_received = True
                response.success()
            else:
                response.failure(f"Stream failed with status code: {response.status_code}")

    @task(1)
    def simple_query(self):
        """Simulate a simple non-streaming query."""
        payload = {
            "query": "Hello world",
            "options": {
                "stream": False,
                "include_trace": False
            }
        }
        with self.client.post("/v1/query", json=payload, headers=self.headers, catch_response=True) as response:
            if response.status_code == 200:
                 response.success()
            else:
                 response.failure(f"Query failed: {response.status_code}")

class IngestionUser(HttpUser):
    wait_time = between(10, 30)

    def on_start(self):
        self.headers = {"X-API-Key": "amber-dev-key-2024"}

    @task
    def upload_document(self):
        """Simulate document upload."""
        # Create a dummy PDF or text file content
        files = {'file': ('test_doc.txt', 'This is a load test document content.', 'text/plain')}

        with self.client.post("/v1/documents", files=files, headers=self.headers, catch_response=True) as response:
             if response.status_code in [200, 201, 202]:
                 response.success()
             else:
                 response.failure(f"Upload failed: {response.status_code}")

