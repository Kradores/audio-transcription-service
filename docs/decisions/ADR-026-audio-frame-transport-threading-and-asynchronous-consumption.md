# ADR-026: Audio Frame Transport Threading and Asynchronous Consumption

## Decision
The ADR should capture the actual decision we're now implementing: a bounded `queue.Queue` provides the thread-safe producer boundary, while `asyncio.to_thread()` bridges blocking consumption into the asynchronous application layer, with a sentinel-based shutdown mechanism and observable dropped-frame accounting.