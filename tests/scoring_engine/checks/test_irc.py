from scoring_engine.engine.basic_check import CHECKS_BIN_PATH

from tests.scoring_engine.checks.check_test import CheckTest


class TestIRCCheck(CheckTest):
    check_name = "IRCCheck"
    properties = {"timeout": "5", "realname": "Scoring Engine"}
    accounts = {"testuser": "testpass"}
    cmd = (
        CHECKS_BIN_PATH
        + "/irc_check 127.0.0.1 1234 5 testuser testuser 'Scoring Engine' testpass"
    )
