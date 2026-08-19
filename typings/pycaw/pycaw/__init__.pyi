from app.audio.windows_device_monitor import _EndpointNotificationEnumerator

class AudioUtilities:
    @staticmethod
    def GetDeviceEnumerator() -> _EndpointNotificationEnumerator: ...
