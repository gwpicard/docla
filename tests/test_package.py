import doclo


def test_version_is_a_non_empty_string():
    assert isinstance(doclo.__version__, str)
    assert doclo.__version__
