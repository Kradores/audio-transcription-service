## runtime concerns:
Windows required
WASAPI available
default render device required
device loss is recoverable
device changes are followed automatically
application remains alive during recovery

## SQLite

Transcript persistence uses a local SQLite database.

The database location is configured through `database.path`.

The configured database directory must be writable by the application.
The application creates the configured parent directory when it does not
already exist.

No external database service is required.