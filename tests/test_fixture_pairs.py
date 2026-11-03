from support.fixtures import missing_pairs


def test_every_rule_has_fail_and_pass_fixture():
    assert missing_pairs() == []
