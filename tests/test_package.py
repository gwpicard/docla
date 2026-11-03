import docla


def test_version_is_a_non_empty_string():
    assert isinstance(docla.__version__, str)
    assert docla.__version__
