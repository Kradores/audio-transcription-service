## First rule
I don't want tests to just verify behavior - I want them to describe the component.

## Test structure
```
tests/
└── unit/
    └── core/
        └── config/
            ├── test_loader.py
            ├── test_models.py
            └── fixtures/
                ├── valid_config.yaml
                ├── invalid_yaml.yaml
                ├── missing_section.yaml
                ├── invalid_sample_rate.yaml
                └── unknown_property.yaml
```

## Test philosophy
- Loads a valid configuration
- Raises `ConfigurationFileNotFoundError`
- Raises `ConfigurationParsingError`
- Raises `ConfigurationValidationError`
- Resolves relative paths
- Leaves absolute paths unchanged

## Test naming
Use this format consistently:
```
def test_load_returns_settings_for_valid_configuration() -> None:
```

