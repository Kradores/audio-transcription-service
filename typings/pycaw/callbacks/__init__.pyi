class MMNotificationClient:
    def on_default_device_changed(
            self,
            flow: str,
            flow_id: int,
            role: str,
            role_id: int,
            default_device_id: str | None,
        ) -> None:
            ...