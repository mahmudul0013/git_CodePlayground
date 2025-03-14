import pytest
from pycomm3 import LogixDriver

# PLC Connection Settings
PLC_IP = '10.64.28.97'  # Replace with your Echo Server IP

@pytest.fixture(scope="module")
def plc():
    """Fixture to establish a connection to the PLC"""
    with LogixDriver(PLC_IP) as plc:
        assert plc.connected, "Failed to connect to PLC"
        yield plc  # Provide PLC connection to tests
