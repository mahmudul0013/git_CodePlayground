import pytest

if __name__ == "__main__":
    # Run all tests in the "tests" folder
    pytest.main(["-v", "tests", '--html=report.html' '--self-contained-html.html'])
