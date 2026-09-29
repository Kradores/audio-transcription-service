from setuptools import setup  # type: ignore[import-untyped]

setup(
    cffi_modules=[
        "build_pipewire.py:ffibuilder",
    ],
)
