import subprocess
import json

def check_outdated_packages():
    """
    Check for outdated Python packages using pip's JSON format output.
    Returns a list of package names that have newer versions available.
    """
    try:
        # Use pip's JSON format for structured output
        output = subprocess.check_output(
            ['pip', 'list', '--outdated', '--format=json'],
            text=True,
            stderr=subprocess.DEVNULL
        )
        data = json.loads(output)
        # Extract package names from the JSON response
        return [item['name'] for item in data]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        # Return empty list on any parsing or execution error
        return []