import pytest

from atendeio.errors import ValidationError
from atendeio.services import rtsp
from atendeio.vision.inventory import summarize


def test_rtsp_url_escapes_credentials():
    url = rtsp.build_url("192.168.1.50", 554, "adm in", "p@ss:w/rd#1", "stream1")
    assert url == "rtsp://adm%20in:p%40ss%3Aw%2Frd%231@192.168.1.50:554/stream1"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "169.254.169.254", "0.0.0.0"])
def test_rtsp_blocks_loopback_and_metadata(host):
    with pytest.raises(ValidationError):
        rtsp.validate(host, 554, "")


def test_rtsp_allows_private_lan():
    assert rtsp.validate("192.168.1.50", "554", "/stream1") == ("192.168.1.50", 554, "stream1")


@pytest.mark.parametrize("bad", [("a b", 554, ""), ("192.168.1.5", 0, ""), ("192.168.1.5", 554, "x y;rm")])
def test_rtsp_rejects_malformed(bad):
    with pytest.raises(ValidationError):
        rtsp.validate(*bad)


def test_inventory_counts():
    dets = [{"name": "person"}, {"name": "person"}, {"name": "chair"}]
    inv = summarize(dets)
    assert inv["total"] == 3
    assert inv["counts"] == [{"name": "person", "count": 2}, {"name": "chair", "count": 1}]
