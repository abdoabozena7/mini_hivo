"""Real-browser verifier regressions; opt in with an existing executable only."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import mini

@unittest.skipUnless(os.environ.get("HIVO_TEST_BROWSER_EXECUTABLE"), "Existing test browser executable not specified")
class BrowserImplicitFaviconTests(unittest.TestCase):
    def setUp(self):
        self.saved = {n:getattr(mini,n) for n in ("WORKSPACE","RUN","RUN_ID")}
        self.temp=tempfile.TemporaryDirectory();mini.WORKSPACE=Path(self.temp.name)
        mini.reset_run("recursive");mini._load_optional_imports()
        self.launch=patch.object(mini,"browser_launch_kwargs",return_value={"headless":True,"executable_path":os.environ["HIVO_TEST_BROWSER_EXECUTABLE"]})
        self.launch.start()
    def tearDown(self):
        self.launch.stop()
        for n,v in self.saved.items():setattr(mini,n,v)
        self.temp.cleanup()
    def snapshot(self, head="", script=""):
        (mini.WORKSPACE/"index.html").write_text("<!doctype html><html><head><title>Verifier fixture</title>"+head+"</head><body><p>Healthy content</p>"+script+"</body></html>",encoding="utf-8")
        return mini.browser_workspace_snapshot("index.html")
    def test_implicit_missing_favicon_does_not_fail_healthy_document(self):
        result=self.snapshot()
        self.assertTrue(result["passed"],result)
        self.assertEqual(result["page_errors"],[])
    def test_explicit_missing_favicon_remains_a_failure(self):
        result=self.snapshot(head='<link rel="icon" href="/favicon.ico">')
        self.assertFalse(result["passed"],result)
        self.assertTrue(result["console_errors"])
    def test_missing_application_script_remains_a_failure(self):
        result=self.snapshot(script='<script src="/missing-application.js"></script>')
        self.assertFalse(result["passed"],result)
        self.assertTrue(result["network_errors"])
    def test_application_console_error_remains_a_failure(self):
        result=self.snapshot(script='<script>console.error("Real application defect");</script>')
        self.assertFalse(result["passed"],result)
        self.assertIn("Real application defect",result["console_errors"])

    def test_explicit_application_request_named_favicon_remains_a_failure(self):
        result=self.snapshot(script='<script src="/favicon.ico"></script>')
        self.assertFalse(result["passed"],result)
        self.assertTrue(result["console_errors"])
