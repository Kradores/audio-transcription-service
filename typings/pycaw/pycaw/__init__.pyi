from app.platforms.windows.audio.device_monitor import _EndpointNotificationEnumerator

class AudioUtilities:
    @staticmethod
    def GetDeviceEnumerator() -> _EndpointNotificationEnumerator: ...
