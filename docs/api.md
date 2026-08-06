## Error messages
Every exception message should help the user fix the problem.

How not to do:
```
Validation failed.
```
The right way:
```
Invalid configuration in 'config/config.yaml': audio.sample_rate must be greater than or equal to 8000.
```