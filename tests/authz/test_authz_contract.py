"""Contract checks on cedar/: files vs template statements, schema shape, README quotes."""

import json
import re
from pathlib import Path

import cedarpy
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CEDAR = ROOT / "cedar"
POLICY_NAMES = ["PermitDevRemediation", "ForbidDestructive", "ForbidProd", "ForbidScaleAboveCap"]


class CfnLoader(yaml.SafeLoader):
    """SafeLoader that keeps CloudFormation short-form tags (!Ref, !Sub, ...) as plain values."""


def _tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    return {tag_suffix: loader.construct_mapping(node)}


CfnLoader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def template() -> dict:
    return yaml.load((CEDAR / "template.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads((CEDAR / "schema.json").read_text(encoding="utf-8"))


def policy_file(name: str) -> bytes:
    return (CEDAR / "policies" / f"{name}.cedar").read_bytes()


def test_only_the_four_policy_files_exist():
    assert sorted(p.stem for p in (CEDAR / "policies").glob("*.cedar")) == sorted(POLICY_NAMES)


def test_policy_files_use_lf_line_endings():
    for name in POLICY_NAMES:
        assert b"\r" not in policy_file(name), f"{name}.cedar must use LF line endings"


@pytest.mark.parametrize("name", POLICY_NAMES)
def test_statement_is_byte_identical_to_cedar_file(template, name):
    res = template["Resources"][name]
    assert res["Type"] == "AWS::VerifiedPermissions::Policy"
    assert res["Properties"]["PolicyStoreId"] == {"Ref": "PolicyStore"}
    statement = res["Properties"]["Definition"]["Static"]["Statement"]
    assert statement.encode("utf-8") == policy_file(name)


def test_policy_store_and_outputs(template):
    store = template["Resources"]["PolicyStore"]
    assert store["Type"] == "AWS::VerifiedPermissions::PolicyStore"
    assert store["Properties"]["ValidationSettings"]["Mode"] == "STRICT"
    assert template["Outputs"]["PolicyStoreId"]["Value"] == {"Ref": "PolicyStore"}
    assert "PolicyIdMap" in template["Outputs"]
    policy_resources = [k for k, v in template["Resources"].items() if v["Type"].endswith("::Policy")]
    assert sorted(policy_resources) == sorted(POLICY_NAMES)


def test_inline_schema_equals_schema_json(template, schema):
    inline = json.loads(template["Resources"]["PolicyStore"]["Properties"]["Schema"]["CedarJson"])
    assert inline == schema


def test_schema_shape(schema):
    ns = schema["Leash"]
    assert sorted(ns["entityTypes"]) == ["Agent", "AutoScalingGroup", "EcsService", "Instance"]
    assert ns["entityTypes"]["Agent"]["shape"]["attributes"] == {}
    for rtype in ("Instance", "EcsService", "AutoScalingGroup"):
        assert ns["entityTypes"][rtype]["shape"]["attributes"] == {"env": {"type": "String"}}
    actions = ns["actions"]
    assert sorted(actions) == ["cleanDisk", "deleteResource", "restartService", "scaleGroup", "terminateInstance"]
    applies = {a: sorted(v["appliesTo"]["resourceTypes"]) for a, v in actions.items()}
    assert applies == {
        "cleanDisk": ["Instance"],
        "restartService": ["EcsService"],
        "scaleGroup": ["AutoScalingGroup"],
        "terminateInstance": ["Instance"],
        "deleteResource": ["AutoScalingGroup", "EcsService", "Instance"],
    }
    for a in actions.values():
        assert a["appliesTo"]["principalTypes"] == ["Agent"]
    ctx = actions["scaleGroup"]["appliesTo"]["context"]["attributes"]
    assert ctx == {"desiredCapacity": {"type": "Long"}}


def test_policies_validate_against_schema(schema):
    joined = "\n".join(policy_file(n).decode("utf-8") for n in POLICY_NAMES)
    result = cedarpy.validate_policies(joined, schema)
    assert result.validation_passed, [str(e) for e in result.errors]


def test_readme_quotes_match_policy_files():
    """README.md shows the policies as ```cedar blocks headed by '// <Name>.cedar'."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = dict(re.findall(r"```cedar\n// (\w+)\.cedar\n(.*?)```", readme, flags=re.S))
    assert sorted(blocks) == sorted(POLICY_NAMES)
    for name, body in blocks.items():
        assert body.strip() == policy_file(name).decode("utf-8").strip(), name
