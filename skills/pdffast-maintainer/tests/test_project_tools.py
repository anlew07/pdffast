"""Offline smoke tests: code map, radar metadata, safe profile draft."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py"))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
idx=load("project_index");radar=load("technology_radar");profile=load("upgrade_profile")
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/"pdffast").mkdir()
        (self.root/"pdffast/parser.py").write_text("from pdffast.result import ParseResult\nclass PDFFastParser:\n def parse(self,pdf): return pdf\n")
        (self.root/"configs").mkdir()
        (self.root/"configs/providers.json").write_text(json.dumps({"providers":{"old":{},"new":{}}}))
        self.template=self.root/"template.json"
        self.template.write_text(json.dumps({"chains":{r:["old"] for r in profile.ROUTES}}))
    def test_index(self):
        data=idx.scan(self.root)
        self.assertTrue(idx.match(data,"PDFFastParser"))
        self.assertIn("parser.py",idx.markdown(data))
    def test_radar_offline(self):
        data=radar.collect(online=False)
        self.assertTrue(data["rows"]);self.assertFalse(any(x["live_checked"] for x in data["rows"]))
    def test_profile_is_unvalidated(self):
        data=profile.draft(self.root,self.template,"old","new","PAGE_DOCUMENT_OCR")
        self.assertEqual(data["chains"]["PAGE_DOCUMENT_OCR"],["new"])
        self.assertEqual(data["chains"]["INLINE_CONTEXT_PARSE"],["old"])
        self.assertIn("UNVALIDATED",data["name"])
    def test_profile_missing_candidate(self):
        with self.assertRaises(ValueError):
            profile.draft(self.root,self.template,"old","missing","PAGE_DOCUMENT_OCR")
if __name__=="__main__":unittest.main()
