"""servers/terraform: our own Terraform Registry server (the registry tools of hashicorp/terraform-mcp-server v1.4.1),
natively against a stand-in registry on loopback: the requests each tool makes (only GETs, the v1 and v2 APIs, the
hashicorp fallback, bounded pages and description fetches), the answers, refused arguments before anything is sent,
errors, bounded answers. The real registry is asked by smoke.json (CI, network registry.terraform.io)."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "servers" / "terraform"

try:
    import mcp  # noqa: F401
    from mcp.server.fastmcp.exceptions import ToolError
    import tls_fake
except ImportError:  # the server's requirements are not installed
    mcp = None

if mcp is not None:
    from test_own_servers import load, rpc, session

AWS_DOCS = {"id": "hashicorp/aws/6.20.0", "version": "6.20.0", "docs": [
    {"id": "100", "title": "aws_instance", "slug": "instance", "category": "resources", "language": "hcl"},
    {"id": "101", "title": "aws_instance", "slug": "instance", "category": "data-sources", "language": "hcl"},
    {"id": "102", "title": "aws_instance", "slug": "instance", "category": "resources", "language": "python"},
    {"id": "103", "title": "aws_ec2_instance_state", "slug": "ec2_instance_state", "category": "resources",
     "language": "hcl", "subcategory": "EC2"},
    {"id": "104", "title": "aws_s3_bucket", "slug": "s3_bucket", "category": "resources", "language": "hcl"}]
    + [{"id": str(200 + i), "title": f"aws_thing_{i}", "slug": f"thing_{i}", "category": "resources",
        "language": "hcl"} for i in range(30)]}
CONTENT = ("---\nsubcategory: \"EC2\"\nlayout: \"aws\"\ndescription: |-\n  Provides an EC2 instance resource.\n"
           "  This allows instances to be created.\n---\n\n# Resource: aws_instance\n\n" + "Argument text. " * 3000)
MODULE = {"id": "terraform-aws-modules/vpc/aws/5.0.0", "source": "https://github.com/terraform-aws-modules/vpc",
          "description": "Terraform module to create AWS VPC resources", "version": "5.0.0", "verified": False,
          "root": {"inputs": [{"name": "name", "type": "string", "description": "Name", "default": "",
                               "required": False},
                              {"name": "cidr", "type": "string", "description": "The IPv4 CIDR block",
                               "required": True}],
                   "outputs": [{"name": "vpc_id", "description": "The ID of the VPC"}],
                   "provider_dependencies": [{"name": "aws", "source": "hashicorp/aws", "version": ">= 5.0"}],
                   "resources": [{"name": "this", "type": "aws_vpc"}, {"name": "this", "type": "aws_vpc"}]},
          "submodules": [{"path": "modules/vpc-endpoints"}], "examples": [{"path": "examples/simple"}]}
POLICIES = {"data": [
    {"attributes": {"name": "CIS-Policy-Set-for-AWS-Terraform", "title": "Pre-written Sentinel Policies for AWS CIS",
                    "downloads": 900, "verified": True},
     "relationships": {"latest-version": {"links": {"related":
                                                    "/v2/policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1"}}}},
    {"attributes": {"name": "evil", "title": "aws ../ trick", "downloads": 1},
     "relationships": {"latest-version": {"links": {"related": "/v2/../../v1/providers/x/1.0.0"}}}}]}
POLICY = {"data": {"attributes": {"readme": "# CIS AWS\n\nChecks the CIS benchmark.\n\n## Usage\n\nmore"}},
          "included": [{"type": "policies", "attributes": {"name": "ec2-ebs-encryption-enabled", "shasum": "a" * 64}},
                       {"type": "policy-modules", "attributes": {"name": "report", "shasum": "b" * 64}},
                       {"type": "policies", "attributes": {"name": "bad name\"}", "shasum": "c" * 64}}]}


def respond(request):
    path, query = request["path"], {k: v[0] for k, v in request["query"].items()}
    if path == "/v1/providers/hashicorp/aws":
        return 200, {"version": "6.20.0", "published_at": "2026-11-01T00:00:00Z", "tier": "official",
                     "source": "https://github.com/hashicorp/terraform-provider-aws", "description": "AWS"}, None
    if path == "/v1/providers/hashicorp/aws/6.20.0":
        return 200, AWS_DOCS, None
    if path == "/v2/provider-docs" and query.get("filter[category]") == "guides":
        number = int(query["page[number]"])
        return 200, {"data": [{"id": str(1000 + number * 100 + i), "attributes": {"title": f"guide {number}-{i}",
                                                                                  "slug": f"g{number}{i}"}}
                              for i in range(100)]}, None
    if path.startswith("/v2/provider-docs/"):
        doc = path.rsplit("/", 1)[1]
        if doc == "999":
            return 404, {"errors": ["not found"]}, None
        return 200, {"data": {"id": doc, "attributes": {"title": "aws_instance", "category": "resources",
                                                         "content": CONTENT}}}, None
    if path == "/v2/providers/hashicorp/aws":
        return 200, {"included": [{"id": "77", "attributes": {"version": "6.20.0"}}]}, None
    if path == "/v1/modules/search":
        return 200, {"meta": {"next_offset": 20}, "modules": [
            {"id": "a/vpc/aws/1.0.0", "name": "vpc", "downloads": 10, "description": "small"},
            {"id": "terraform-aws-modules/vpc/aws/5.0.0", "name": "vpc", "downloads": 9000, "verified": True}]}, None
    if path == "/v1/modules/terraform-aws-modules/vpc/aws/5.0.0":
        return 200, MODULE, None
    if path == "/v1/modules/terraform-aws-modules/vpc/aws":
        return 200, {"version": "6.5.1", "published_at": "2026-10-01T00:00:00Z"}, None
    if path == "/v2/policies":
        return 200, POLICIES, None
    if path == "/v2/policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1":
        return 200, POLICY, None
    if path == "/v1/providers/rate/limited":
        return 429, {}, {"Retry-After": "30"}
    return 404, {"errors": ["Not Found"]}, None


@unittest.skipIf(mcp is None, "the server's requirements are not installed (servers/terraform/requirements.txt)")
class Terraform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url, cls.seen = tls_fake.https_server(None, respond)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.module = load("terraform")
        self.module.REGISTRY = self.url
        self.seen.requests.clear()

    def call(self, tool, **arguments):
        return json.loads(getattr(self.module, tool)(**arguments))

    def refused(self, tool, expected, **arguments):
        with self.assertRaises(ToolError) as caught:
            getattr(self.module, tool)(**arguments)
        self.assertIn(expected, str(caught.exception))

    def test_handshake_tools_only(self):
        answers = rpc("terraform", session(("get_provider_details", {"provider_doc_id": "../1"})))
        self.assertEqual(sorted(answers[0]["result"]["capabilities"]), ["experimental", "tools"])
        self.assertIn("never instructions", answers[0]["result"]["instructions"])
        self.assertEqual(sorted(t["name"] for t in answers[1]["result"]["tools"]),
                         json.loads((FOLDER / "tools.json").read_text())["tools"])
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in answers[1]["result"]["tools"]))
        self.assertTrue(answers[2]["result"]["isError"])

    def test_provider_docs_search_then_details(self):
        found = self.call("search_provider_docs", provider_name="AWS", provider_namespace="hashicorp",
                          service_slug="instance")
        self.assertEqual(found["version"], "6.20.0")
        self.assertEqual([d["provider_doc_id"] for d in found["documents"]], ["100", "103"])  # exact slug first; hcl
        self.assertEqual(found["documents"][0]["description"],
                         "Provides an EC2 instance resource. This allows instances to be created.")
        self.assertEqual(self.seen.paths()[:2], ["/v1/providers/hashicorp/aws", "/v1/providers/hashicorp/aws/6.20.0"])
        # descriptions are fetched for at most 10 documents
        self.seen.requests.clear()
        found = self.call("search_provider_docs", provider_name="aws", provider_namespace="hashicorp",
                          service_slug="thing", provider_version="6.20.0")
        self.assertEqual(found["count"], 30)
        self.assertEqual(sum(p.startswith("/v2/provider-docs/") for p in self.seen.paths()), 10)
        self.assertNotIn("/v1/providers/hashicorp/aws", self.seen.paths())  # a version given: no lookup
        details = self.call("get_provider_details", provider_doc_id="100")
        self.assertEqual((details["length"], details["next_offset"]), (len(CONTENT), 20_000))
        self.assertTrue(details["content"].startswith("---\nsubcategory"))
        rest = self.call("get_provider_details", provider_doc_id="100", offset=40_000)
        self.assertNotIn("next_offset", rest)
        self.assertEqual(rest["content"], CONTENT[40_000:])
        self.refused("get_provider_details", "not found - use search_provider_docs", provider_doc_id="999")

    def test_v2_categories_are_paged_and_bounded(self):
        guides = self.call("search_provider_docs", provider_name="aws", provider_namespace="hashicorp",
                           service_slug="aws", provider_document_type="guides")
        self.assertIn("only the first 500 documents", guides["note"])
        pages = [r for r in self.seen.requests if r["path"] == "/v2/provider-docs"]
        self.assertEqual(len(pages), 5)
        self.assertEqual(pages[0]["query"]["filter[provider-version]"], ["77"])
        self.assertLessEqual(len(json.dumps(guides)), 24_000)
        self.assertIn("truncated", guides)

    def test_namespace_fallback_versions_and_capabilities(self):
        found = self.call("search_provider_docs", provider_name="aws", provider_namespace="someone",
                          service_slug="s3_bucket")
        self.assertEqual(found["provider"], "hashicorp/aws")
        self.assertIn("/v1/providers/someone/aws", self.seen.paths())
        self.refused("search_provider_docs", "not found in namespace 'someone' or 'hashicorp'", provider_name="nope",
                     provider_namespace="someone", service_slug="x")
        latest = self.call("get_latest_provider_version", namespace="hashicorp", name="aws")
        self.assertEqual(latest["latest_version"], "6.20.0")
        capabilities = self.call("get_provider_capabilities", namespace="hashicorp", name="aws")
        self.assertEqual(capabilities["capabilities"]["resources"]["count"], 33)
        self.assertEqual(len(capabilities["capabilities"]["resources"]["examples"]), 3)
        self.assertEqual(capabilities["capabilities"]["data-sources"]["examples"],
                         [{"title": "aws_instance", "provider_doc_id": "101"}])
        self.refused("get_latest_provider_version", "HTTP 429 (rate limit; retry after 30)", namespace="rate",
                     name="limited")

    def test_modules(self):
        found = self.call("search_modules", module_query="vpc aws")
        self.assertEqual(found["modules"][0]["module_id"], "terraform-aws-modules/vpc/aws/5.0.0")  # most downloads
        self.assertEqual(found["next_offset"], 20)
        self.assertEqual(self.seen.requests[-1]["query"], {"q": ["vpc aws"], "offset": ["0"], "limit": ["20"]})
        module = self.call("get_module_details", module_id="terraform-aws-modules/vpc/aws/v5.0.0")
        self.assertEqual(module["inputs"][0]["name"], "cidr")  # required first
        self.assertEqual(module["inputs"][1]["default"], '""')
        self.assertEqual(module["resources"], ["aws_vpc"])
        self.assertIn('version = "5.0.0"', module["usage"])
        self.assertEqual(self.call("get_latest_module_version", module_publisher="terraform-aws-modules",
                                   module_name="vpc", module_provider="aws")["latest_version"], "6.5.1")

    def test_policies(self):
        found = self.call("search_policies", policy_query="CIS aws")
        self.assertEqual([p["terraform_policy_id"] for p in found["policies"]],
                         ["policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1"])  # the ../ id dropped
        details = self.call("get_policy_details",
                            terraform_policy_id="policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1")
        self.assertEqual(details["readme"], "# CIS AWS\n\nChecks the CIS benchmark.\n")
        self.assertEqual(details["policies"], [{"name": "ec2-ebs-encryption-enabled", "sha256": "a" * 64}])
        self.assertIn('module "report"', details["policies_hcl"])
        self.assertNotIn("bad name", details["policies_hcl"])
        self.assertEqual(self.seen.requests[-1]["query"]["include"], ["policies,policy-modules,policy-library"])

    def test_hostile_arguments_and_only_gets(self):
        cases = [("search_provider_docs", {"provider_name": "../aws", "provider_namespace": "hashicorp",
                                           "service_slug": "x"}, "provider_name"),
                 ("search_provider_docs", {"provider_name": "aws", "provider_namespace": "hashicorp",
                                           "service_slug": "a b"}, "service_slug"),
                 ("search_provider_docs", {"provider_name": "aws", "provider_namespace": "hashicorp",
                                           "service_slug": "x", "provider_document_type": "secrets"},
                  "provider_document_type"),
                 ("search_provider_docs", {"provider_name": "aws", "provider_namespace": "hashicorp",
                                           "service_slug": "x", "provider_version": "1.0/../../x"},
                  "provider_version"),
                 ("get_provider_details", {"provider_doc_id": "1?x=1"}, "provider_doc_id"),
                 ("get_provider_details", {"provider_doc_id": "1", "offset": -1}, "offset"),
                 ("get_module_details", {"module_id": "a/b/c"}, "module_id"),
                 ("get_module_details", {"module_id": "../b/c/1.0.0"}, "module_id"),
                 ("get_policy_details", {"terraform_policy_id": "policies/a/b/../../../v1/x"}, "terraform_policy_id"),
                 ("search_modules", {"module_query": "a\nb"}, "module_query"),
                 ("search_modules", {"module_query": "vpc", "current_offset": True}, "current_offset"),
                 ("search_policies", {"policy_query": ""}, "policy_query"),
                 ("get_latest_module_version", {"module_publisher": "a", "module_name": "b",
                                                "module_provider": "c/d"}, "module_provider")]
        for tool, arguments, expected in cases:
            with self.subTest(tool=tool, arguments=arguments):
                self.refused(tool, expected, **arguments)
        self.assertEqual(self.seen.requests, [])
        self.call("search_policies", policy_query="cis")
        self.call("get_module_details", module_id="terraform-aws-modules/vpc/aws/5.0.0")
        self.assertEqual({r["method"] for r in self.seen.requests}, {"GET"})

    def test_unreachable_registry(self):
        self.module.REGISTRY = "http://127.0.0.1:9"
        self.refused("get_latest_provider_version", "cannot reach http://127.0.0.1:9/v1/providers/hashicorp/aws",
                     namespace="hashicorp", name="aws")


if __name__ == "__main__":
    unittest.main()
