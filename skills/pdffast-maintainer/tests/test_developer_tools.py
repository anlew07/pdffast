"""Source navigation and trial Provider safety tests (offline, no OCR model)."""
import importlib.util,sys,tempfile,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from change_impact import impact
from candidate_scaffold import scaffold
from experiment_config import assemble
from propose_profile import propose,ROUTES
class Tests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.d=Path(t.name);self.repo=self.d/"repo";(self.repo/"pdffast").mkdir(parents=True)
        (self.repo/"pdffast/parser.py").write_text("class PDFFastParser:\n def parse(self): pass\n")
        (self.repo/"pdffast/other.py").write_text("from pdffast.parser import PDFFastParser\n")
        (self.repo/"configs").mkdir()
        (self.repo/"configs/providers.json").write_text(json.dumps({"providers":{"old":{"runtime_enabled":True}}}))
    def test_map(self):
        x=impact(self.repo,"PDFFastParser")
        self.assertEqual(x["status"],"LOCATED")
        self.assertIn("pdffast/other.py",x["direct_importers"])
    def test_scaffold_and_private_config(self):
        path=self.d/"private"
        r=scaffold("fresh_ocr",path,"PAGE_DOCUMENT_OCR")
        self.assertFalse(r["production_ready"])
        cfg=assemble(self.repo,path/"registry-fragment.json",self.d/"config.json")
        self.assertFalse(cfg["production_changed"])
        self.assertNotIn("fresh_ocr",json.loads((self.repo/"configs/providers.json").read_text())["providers"])
        with self.assertRaises(ValueError):scaffold("fresh_ocr",path,"PAGE_DOCUMENT_OCR")
    def test_gate_identity(self):
        p={"chains":{r:["old"] for r in ROUTES}}
        cfg={"providers":{"old":{"runtime_enabled":True},"new":{"runtime_enabled":True}}}
        gate={"decision":"READY_FOR_END_TO_END","production_ready":False,
              "baseline_provider":"not_old","candidate_provider":"new"}
        with self.assertRaises(ValueError):
            propose(p,cfg,gate,"PAGE_DOCUMENT_OCR","old","new")
        gate["baseline_provider"]="old"
        self.assertEqual(propose(p,cfg,gate,"PAGE_DOCUMENT_OCR","old","new")["chains"]["PAGE_DOCUMENT_OCR"][0],"new")
if __name__=="__main__":unittest.main()