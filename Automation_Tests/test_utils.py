def compare_structs(struct1, struct2, float_precision=2):
    """
    Compare two dictionaries representing PLC structs.
    Floats are compared up to `float_precision` decimal places.
    
    :param struct1: First struct as a dictionary
    :param struct2: Second struct as a dictionary
    :param float_precision: Number of decimal places for float comparison
    :return: True if structs are equal, False otherwise
    """
    if struct1.keys() != struct2.keys():
        return False  # Structs have different fields

    for key in struct1:
        val1, val2 = struct1[key], struct2[key]

        if isinstance(val1, float) and isinstance(val2, float):
            # Compare floats up to specified decimal places
            if round(val1, float_precision) != round(val2, float_precision):
                print(f"Mismatch: {key} -> {val1} != {val2} (rounded)")
                return False

        elif val1 != val2:
            print(f"Mismatch: {key} -> {val1} != {val2}")
            return False

    return True
