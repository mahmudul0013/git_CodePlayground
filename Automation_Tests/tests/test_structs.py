from test_utils import compare_structs

def test_struct_read(plc):
    """Test reading a structured tag (UDT)"""
    struct_name = "P2016"  # Example struct
    struct_data = plc.read(struct_name)
    
    # assert isinstance(struct_data, dict), "Struct read failed"
    assert "Value" in struct_data.value, "Field1 missing in struct"
    assert "Default" in struct_data.value, "Field2 missing in struct"
    
    print(f"Struct data: {struct_data}")

def test_struct_write(plc):
    """Test writing to a structured tag"""
    struct_name = "P2016"

    # Read old and change value of some of the fields
    struct_values = plc.read(struct_name).value
    struct_values["Value"] = 100
    struct_values["Default"] = 3.14
    struct_values["Desc"] = "Korv"

    write_result = plc.write(struct_name, struct_values)
    assert write_result, "Failed to write struct"
    
    # Verify
    struct_data = plc.read(struct_name)
    floating_point_precision = 4
    assert compare_structs(struct_data.value, struct_values, floating_point_precision), f"Struct verification failed: expected {struct_values}, got {struct_data}"

