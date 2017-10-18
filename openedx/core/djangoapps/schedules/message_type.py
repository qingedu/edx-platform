import logging

from edx_ace.message import MessageType

from openedx.core.djangoapps.schedules.config import DEBUG_MESSAGE_WAFFLE_FLAG


class ScheduleMessageType(MessageType):
    def __init__(self, *args, **kwargs):
        super(ScheduleMessageType, self).__init__(*args, **kwargs)
        self.log_level = logging.DEBUG if DEBUG_MESSAGE_WAFFLE_FLAG.is_enabled() else None
