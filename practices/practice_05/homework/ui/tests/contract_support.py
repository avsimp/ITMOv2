"""Validate against the single agreed YAML, not a second editable schema."""
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts/api-v1.yaml").read_text())
assert CONTRACT["info"]["version"] == "1.0.0"
assert CONTRACT["x-contract-status"] == "agreed"


def validate(value, name):
    schema = {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value
