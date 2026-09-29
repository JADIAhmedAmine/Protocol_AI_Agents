"""Exercise the running Gradio UI backend with the actual local model."""
import json
from urllib.request import urlopen
from gradio_client import Client


def main():
    with urlopen("http://127.0.0.1:7860/", timeout=30) as response:
        assert response.status == 200
    client = Client("http://127.0.0.1:7860", verbose=False)
    status = client.predict(api_name="/model_status")
    assert "ready" in status
    result = client.predict("The archive opens at 09:00.", "The archive opens at 09:00 and closes at 17:00.",
        api_name="/review_claim")
    summary, rows, audit, artifact = result
    assert "protocol deliberative" in summary
    assert audit["review"]["phase"] in ("closed", "arbitration")
    assert len(rows["data"]) == 6
    assert artifact
    print(json.dumps({"gradio": "passed", "status": status,
        "review_rows": len(rows["data"]), "protocol_outcome": audit["review"]["result"]["outcome"]}, indent=2))


if __name__ == "__main__":
    main()
