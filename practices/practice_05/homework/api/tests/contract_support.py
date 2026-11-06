from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts/api-v1.yaml"
CONTRACT = yaml.safe_load(CONTRACT_PATH.read_text())
assert CONTRACT["info"]["version"] == "1.0.0"
assert CONTRACT["x-contract-status"] == "agreed"
REGISTRY = Registry().with_resource("urn:api", Resource.from_contents(CONTRACT, default_specification=DRAFT202012))


def validate(value, schema):
    Draft202012Validator(
        {"$ref": "urn:api#/components/schemas/" + schema}, registry=REGISTRY, format_checker=FormatChecker()
    ).validate(value)


def error(response, status, code):
    assert response.status_code == status, response.text
    validate(response.json(), "ErrorResponse")
    assert response.json()["error"]["code"] == code
    assert "/Users/" not in response.text and "Traceback" not in response.text
