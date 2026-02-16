from tests.scoring_engine.checks.check_test import CheckTest


class TestActiveDirectoryCheck(CheckTest):
    check_name = "ActiveDirectoryCheck"
    properties = {"domain": "example.com", "base_dn": "dc=example,dc=com"}
    accounts = {"testuser": "testpass"}
    cmd = (
        "ldapsearch -x -H ldap://127.0.0.1:1234 -D testuser@example.com -w testpass "
        "-b dc=example,dc=com '(objectclass=person)' sAMAccountName"
    )
