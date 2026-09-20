"""机制实验：patch底层故障，真实外层转换仍执行；无网络调用。"""
import json
from unittest.mock import patch
from urllib import error, request

class AuthenticationError(Exception):
    pass

def call_provider():
    try:
        with request.urlopen("https://provider.invalid", timeout=1) as response:
            return response.read()
    except error.HTTPError as exc:
        if exc.code == 401:
            raise AuthenticationError("authentication") from exc
        raise

def main():
    original = request.urlopen
    failure = error.HTTPError("https://provider.invalid", 401, "fixture", None, None)
    observed = None
    with patch.object(request, "urlopen", side_effect=failure) as mocked:
        try:
            call_provider()
        except AuthenticationError as exc:
            observed = type(exc).__name__
        assert observed == "AuthenticationError"
        assert mocked.call_count == 1
        count = mocked.call_count
    assert request.urlopen is original
    print(json.dumps({"scope":"mocked-network", "mapped_error":observed,
                      "call_count":count, "restored":True, "verified":True}))

if __name__ == "__main__":
    main()
