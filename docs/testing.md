## First rule
I don't want tests to just verify behavior - I want them to describe the component.

## Test structure
```
tests/
└── unit/
    └── core/
        └── config/
            ├── builders.py
            ├── helpers.py
            ├── test_loader.py
            ├── test_models.py
            └── fixtures/
                ├── valid_config.yaml
                └── invalid_yaml.yaml
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

## Testing pattern
```
# Arrange

# Act

# Assert
```
One blank line between Arrange, Act and Assert

## What a unit test does
A unit test should verify one component's responsibility. Avoid re-testing behavior already covered by another test suite.
For example:
- `test_loader.py` verifies loading, parsing, validation, and path resolution.
- `test_models.py` verifies field constraints and model behavior.

That separation keeps the tests fast, focused, and easier to maintain.
