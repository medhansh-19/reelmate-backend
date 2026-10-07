import pytest

from app.server import resolve_port


def test_resolve_port_uses_safe_default_and_host_value() -> None:
    assert resolve_port(None) == 8000
    assert resolve_port("") == 8000
    assert resolve_port(" 9000 ") == 9000


@pytest.mark.parametrize("value", ["nope", "0", "65536"])
def test_resolve_port_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="PORT"):
        resolve_port(value)
