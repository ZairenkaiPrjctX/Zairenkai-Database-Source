"""Static checks of buildspec.yml and infra/cloudformation/codebuild.yml: least privilege,
existing bucket only, no webhook, no privileged mode, publishing off by default."""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

import yaml

from tests.pipeline.support import REPO


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that keeps CloudFormation short-form tags as {'Fn::X': value}."""


def _tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
    return {name: value}


_CfnLoader.add_multi_constructor("!", _tag)


def template() -> dict[str, Any]:
    text = (REPO / "infra" / "cloudformation" / "codebuild.yml").read_text()
    return yaml.load(text, Loader=_CfnLoader)  # noqa: S506 - SafeLoader subclass


def statements(doc: dict[str, Any]) -> list[dict[str, Any]]:
    role = doc["Resources"]["BuildRole"]["Properties"]
    return [s for p in role["Policies"] for s in p["PolicyDocument"]["Statement"]]


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


class InfraTest(unittest.TestCase):
    def test_buildspec_is_metadata_only_and_publish_is_off(self) -> None:
        spec = yaml.safe_load((REPO / "buildspec.yml").read_text())
        self.assertEqual(str(spec["version"]), "0.2")
        self.assertEqual(spec["env"]["variables"]["ENABLE_S3_PUBLISH"], "false")
        self.assertEqual(spec["phases"]["install"]["runtime-versions"]["python"], 3.13)
        build = spec["phases"]["build"]["commands"]
        self.assertIn("--mode dry-run", build[0])
        self.assertTrue(
            build[-1].startswith("python tools/publish_manifest.py")
        )  # last, so only after success
        commands = "\n".join(c for phase in spec["phases"].values() for c in phase["commands"])
        for forbidden in (
            "aws configure",
            "docker",
            "git push",
            "curl ",
            "wget ",
            "--mode discover",
            "AWS_SECRET",
            "AWS_ACCESS_KEY",
        ):
            self.assertNotIn(forbidden, commands)
        self.assertNotIn("artifacts", spec)
        self.assertIn("--require-hashes", commands)

    def test_template_uses_existing_bucket_and_creates_no_compute(self) -> None:
        doc = template()
        types = {r["Type"] for r in doc["Resources"].values()}
        self.assertEqual(
            types, {"AWS::Logs::LogGroup", "AWS::IAM::Role", "AWS::CodeBuild::Project"}
        )
        self.assertEqual(
            doc["Parameters"]["StagingBucketName"]["Default"],
            "zairenkai-firmware-staging-20261020-x7k9",
        )
        self.assertEqual(doc["Parameters"]["StagingPrefix"]["Default"], "staging/")
        self.assertNotIn("Default", doc["Parameters"]["CodeConnectionArn"])
        self.assertNotIn("Default", doc["Parameters"]["GitHubRepositoryUrl"])

    def test_project_has_no_webhook_and_no_privileged_mode(self) -> None:
        p = template()["Resources"]["BuildProject"]["Properties"]
        self.assertNotIn("Triggers", p)
        self.assertFalse(p["Environment"]["PrivilegedMode"])
        self.assertFalse(p["Source"]["ReportBuildStatus"])  # no GitHub write access needed
        self.assertFalse(p["Source"]["InsecureSsl"])
        self.assertEqual(p["Source"]["Auth"]["Type"], "CODECONNECTIONS")
        self.assertEqual(p["ConcurrentBuildLimit"], 1)
        self.assertEqual(p["Artifacts"]["Type"], "NO_ARTIFACTS")
        self.assertEqual(p["Visibility"], "PRIVATE")
        env = {v["Name"]: v["Value"] for v in p["Environment"]["EnvironmentVariables"]}
        self.assertEqual(env["ENABLE_S3_PUBLISH"], {"Ref": "EnableS3Publish"})
        self.assertEqual(template()["Parameters"]["EnableS3Publish"]["Default"], "false")

    def test_cloudformation_least_privilege(self) -> None:
        doc = template()
        stmts = statements(doc)
        actions = sorted(a for s in stmts for a in as_list(s["Action"]))
        self.assertEqual(
            actions,
            sorted(
                [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "s3:PutObject",
                    "codeconnections:GetConnection",
                    "codeconnections:GetConnectionToken",
                    "codestar-connections:GetConnection",
                    "codestar-connections:GetConnectionToken",
                ]
            ),
        )
        text = json.dumps(stmts)
        self.assertNotIn('"*"', text)
        self.assertNotRegex(text, r'"(s3|iam|logs|codebuild|\w+):\*"')
        self.assertNotIn("Deny", text)  # nothing relies on deny-overrides
        s3 = next(s for s in stmts if s["Action"] == "s3:PutObject")
        self.assertEqual(
            s3["Resource"],
            {"Fn::Sub": "arn:${AWS::Partition}:s3:::${StagingBucketName}/${StagingPrefix}runs/*"},
        )
        self.assertEqual(
            s3["Condition"]["StringEquals"]["s3:ResourceAccount"], {"Ref": "AWS::AccountId"}
        )
        conn = next(s for s in stmts if "codeconnections:GetConnectionToken" in s["Action"])
        self.assertEqual(conn["Resource"], {"Ref": "CodeConnectionArn"})
        role = doc["Resources"]["BuildRole"]["Properties"]
        self.assertNotIn("ManagedPolicyArns", role)
        trust = role["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual(len(trust), 1)
        self.assertEqual(trust[0]["Principal"], {"Service": "codebuild.amazonaws.com"})
        self.assertIn("aws:SourceAccount", trust[0]["Condition"]["StringEquals"])
        self.assertIn("aws:SourceArn", trust[0]["Condition"]["ArnLike"])

    def test_parameter_validation_patterns(self) -> None:
        params = template()["Parameters"]
        arn = re.compile(params["CodeConnectionArn"]["AllowedPattern"])
        self.assertTrue(
            arn.match(
                "arn:aws:codeconnections:ap-southeast-1:123456789012:connection/0a1b2c3d-4e5f-6789-abcd-ef0123456789"
            )
        )
        for bad in (
            "",
            "arn:aws:iam::123456789012:role/x",
            "arn:aws:codeconnections:ap-southeast-1:123:connection/x",
        ):
            self.assertIsNone(arn.match(bad), bad)
        prefix = re.compile(params["StagingPrefix"]["AllowedPattern"])
        self.assertTrue(prefix.match("staging/"))
        for bad in ("", "staging", "/staging/", "staging/runs/", "../", "Staging/"):
            self.assertIsNone(prefix.match(bad), bad)
        url = re.compile(params["GitHubRepositoryUrl"]["AllowedPattern"])
        self.assertTrue(
            url.match("https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source.git")
        )
        self.assertIsNone(url.match("http://github.com/a/b.git"))
        timeout = params["BuildTimeoutMinutes"]
        self.assertEqual((timeout["Default"], timeout["MaxValue"]), (15, 60))

    def test_arm_condition_selects_the_image_name(self) -> None:
        cond = template()["Conditions"]["IsArm"]["Fn::Equals"]
        self.assertEqual(cond[1], "amazonlinux-aarch64-standard")
        # Mirror of the template's Split/Select: aws/codebuild/<name>:<tag>
        index = cond[0]["Fn::Select"][1]["Fn::Split"][1]["Fn::Select"][0]
        for image in template()["Parameters"]["BuildImage"]["AllowedValues"]:
            name = image.split("/")[index].split(":")[0]
            self.assertEqual(name == cond[1], "aarch64" in image, image)
