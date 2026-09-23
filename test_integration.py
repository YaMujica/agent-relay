from __future__ import annotations

import os
from typing import Generator
import pytest
import httpx

BASE_URL = os.getenv("RELAY_BASE_URL")


@pytest.fixture
def api_client() -> Generator[httpx.Client, None, None]:
    if BASE_URL:
        with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
            yield client
    else:
        from fastapi.testclient import TestClient
        import main
        with TestClient(main.app) as client:
            yield client


def test_agent_task_exchange_flow(api_client: httpx.Client):
    """Scenario 1 from SPEC.md:
    Register two agents. One sends a task; the other claims and completes it;
    the sender reads the result.
    """
    # 1. Register sender (Alice)
    alice_resp = api_client.post("/api/v1/agents", json={"name": "alice"})
    assert alice_resp.status_code == 201, alice_resp.text
    alice = alice_resp.json()
    alice_id = alice["agent_id"]
    alice_headers = {"Authorization": f"Bearer {alice['token']}"}

    # 2. Register recipient (Bob)
    bob_resp = api_client.post("/api/v1/agents", json={"name": "bob"})
    assert bob_resp.status_code == 201, bob_resp.text
    bob = bob_resp.json()
    bob_id = bob["agent_id"]
    bob_headers = {"Authorization": f"Bearer {bob['token']}"}

    # 3. Sender sends a task to Bob
    task_payload = {"to": bob_id, "input": "Hello Bob, please uppercase this"}
    send_resp = api_client.post("/api/v1/tasks", headers=alice_headers, json=task_payload)
    assert send_resp.status_code == 201, send_resp.text
    task_id = send_resp.json()["task_id"]
    assert send_resp.json()["status"] == "queued"

    # Sender checks task status -> must be 'queued'
    check_queued = api_client.get(f"/api/v1/tasks/{task_id}", headers=alice_headers)
    assert check_queued.status_code == 200
    assert check_queued.json()["status"] == "queued"

    # 4. Recipient claims the task
    claim_resp = api_client.post(
        "/api/v1/tasks/claim",
        headers=bob_headers,
        json={"worker_id": "bob-worker-1", "wait_seconds": 0},
    )
    assert claim_resp.status_code == 200, claim_resp.text
    claim_data = claim_resp.json()
    assert claim_data["task_id"] == task_id
    assert claim_data["from"] == alice_id
    assert "claim_token" in claim_data
    claim_token = claim_data["claim_token"]

    # Sender checks task status -> must be 'processing'
    check_processing = api_client.get(f"/api/v1/tasks/{task_id}", headers=alice_headers)
    assert check_processing.status_code == 200
    assert check_processing.json()["status"] == "processing"

    # 5. Recipient submits result / completes the task
    output_text = "HELLO BOB, PLEASE UPPERCASE THIS"
    complete_resp = api_client.post(
        f"/api/v1/tasks/{task_id}/complete",
        headers=bob_headers,
        json={"claim_token": claim_token, "output": output_text},
    )
    assert complete_resp.status_code == 200, complete_resp.text
    assert complete_resp.json()["status"] == "completed"

    # 6. Sender reads the result
    final_task_resp = api_client.get(f"/api/v1/tasks/{task_id}", headers=alice_headers)
    assert final_task_resp.status_code == 200, final_task_resp.text
    final_task = final_task_resp.json()

    # Verify final status seen by sender
    assert final_task["status"] == "completed"
    assert final_task["output"] == output_text
    assert final_task["error"] is None
    assert final_task["finished_at"] is not None

    print(f"\nTask exchange succeeded! Sender sees status: {final_task['status']}")


if __name__ == "__main__":
    import sys
    base = os.getenv("RELAY_BASE_URL", "http://127.0.0.1:8000")
    print(f"Running integration test against {base}...")
    with httpx.Client(base_url=base, timeout=10.0) as client:
        test_agent_task_exchange_flow(client)
    print("All integration test assertions passed successfully!")
