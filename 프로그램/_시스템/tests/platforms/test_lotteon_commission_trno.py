from shared.platforms.lotteon.claims import commission_map
from datetime import datetime

class _FakeClient:
    def __init__(self):
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "LO_ACCT_X", "lrtr_no": ""}
        self.sent = []
    def request(self, method, path, body=None):
        self.sent.append(body)
        return {"data": []}

def test_uses_client_trno_not_module_cfg():
    cli = _FakeClient()
    commission_map(datetime(2026, 7, 1), datetime(2026, 7, 2), client=cli)
    assert cli.sent, "no request was sent"
    assert cli.sent[0]["trNo"] == "LO_ACCT_X"
