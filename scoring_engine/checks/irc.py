from scoring_engine.engine.basic_check import BasicCheck, CHECKS_BIN_PATH


class IRCCheck(BasicCheck):
    required_properties = ['timeout', 'realname']
    CMD = CHECKS_BIN_PATH + '/irc_check {0} {1} {2} {3} {4} {5} {6}'

    def command_format(self, properties):
        account = self.get_random_account()
        return (
            self.host,
            self.port,
            properties['timeout'],
            account.username,
            account.username,
            properties['realname'],
            account.password,
        )
