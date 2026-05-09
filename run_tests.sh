#!/bin/bash

# Run tests with coverage
coverage run -m pytest
coverage report --include="zero/*"

# Check for import errors
python -c "from zero import app"