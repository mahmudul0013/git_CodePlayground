import pytest

@pytest.mark.tags
def test_read_tag(plc):
    """Test reading a tag from the PLC"""
    tag_name = "Simulation"
    value = plc.read(tag_name)
    assert value.value is not None, "Failed to read tag"
    print(f"Read {tag_name}: {value}")

@pytest.mark.tags
def test_write_tag(plc):
    """Test writing a value to a PLC tag"""
    tag_name = "Simulation"
    new_value = True
    write_result = plc.write(tag_name, new_value)
    assert write_result, "Failed to write tag"
    
    # Verify the write operation
    value = plc.read(tag_name)
    assert value.value == new_value, f"Write verification failed: expected {new_value}, got {value}"
